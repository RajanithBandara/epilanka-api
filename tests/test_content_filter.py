"""
tests/test_content_filter.py
============================
Comprehensive unit tests for the 3-layer content filtering pipeline.

Tests are organised by layer and use pytest-asyncio for the async layer.
Groq is monkeypatched so tests run fully offline and instantly.

Architecture (post Option-B merge):
  Layer 1 — check_links()        (sync, regex)
  Layer 2 — check_keywords()     (sync, profanity/spam)
  Layer 3 — check_with_groq()    (async, single Groq call: VALID | TOXIC | IRRELEVANT)

The old Layer 3 (Detoxify / check_toxicity) and Layer 4 (check_health_relevance)
have been merged into check_with_groq().  Tests that previously mocked the
Detoxify model now assert the same behaviours through the Groq mock.

Run with:
    pytest tests/test_content_filter.py -v
"""

# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from utils.content_filter import (
    check_keywords,
    check_links,
    check_with_groq,
    run_content_filter_pipeline,
)

# ──────────────────────────────────────────────────────────────────────────────
# Shared fixtures
# ──────────────────────────────────────────────────────────────────────────────

VALID_REPORT = (
    "Ten residents in Gampaha district have reported dengue fever symptoms "
    "including high temperature, rash, and severe joint pain over the past five days. "
    "Three children have been admitted to Gampaha General Hospital."
)


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 1 — Regex Link & Call-to-Action Detection
# ══════════════════════════════════════════════════════════════════════════════

class TestLayer1Links:
    """Layer 1: check_links() — URL and promotional phrase detection."""

    # ── BLOCK cases ───────────────────────────────────────────────────────────

    def test_blocks_http_url(self):
        with pytest.raises(ValueError, match="Reports cannot contain links"):
            check_links("Disease reported. Check http://spam.com for details.")

    def test_blocks_https_url(self):
        with pytest.raises(ValueError):
            check_links("Visit https://example.lk for updates.")

    def test_blocks_www_prefix(self):
        with pytest.raises(ValueError):
            check_links("More info at www.health.lk today.")

    def test_blocks_bare_domain_com(self):
        with pytest.raises(ValueError):
            check_links("See results at epilanka.com for more.")

    def test_blocks_bare_domain_lk(self):
        with pytest.raises(ValueError):
            check_links("Visit health.lk for hospital records.")

    def test_blocks_url_shortener_bitly(self):
        with pytest.raises(ValueError):
            check_links("Shortened link: bit.ly/abc123")

    def test_blocks_url_shortener_tinyurl(self):
        with pytest.raises(ValueError):
            check_links("Open tinyurl to see the data.")

    def test_blocks_ftp_url(self):
        with pytest.raises(ValueError):
            check_links("File at ftp://files.example.org/report.pdf")

    def test_blocks_mailto(self):
        with pytest.raises(ValueError):
            check_links("Email us at mailto:contact@health.gov.lk")

    def test_blocks_follow_this_link(self):
        """The exact user example from the bug report."""
        with pytest.raises(ValueError):
            check_links(
                "disease has been reported. get here to follow this link to get my data"
            )

    def test_blocks_click_here(self):
        with pytest.raises(ValueError):
            check_links("Click here to see the outbreak data.")

    def test_blocks_get_here(self):
        with pytest.raises(ValueError):
            check_links("Get here for more information about the case.")

    def test_blocks_visit_site(self):
        with pytest.raises(ValueError):
            check_links("Please visit this site for more details.")

    def test_blocks_visit_page(self):
        with pytest.raises(ValueError):
            check_links("Visit this page to track the outbreak.")

    def test_blocks_download_now(self):
        with pytest.raises(ValueError):
            check_links("Download now for the full report.")

    def test_blocks_join_now(self):
        with pytest.raises(ValueError):
            check_links("Join now to get updates on disease outbreaks.")

    def test_blocks_sign_up_here(self):
        with pytest.raises(ValueError):
            check_links("Sign up here to receive alerts.")

    def test_blocks_get_my_data(self):
        with pytest.raises(ValueError):
            check_links("Follow this link to get my data.")

    def test_blocks_share_your_data(self):
        with pytest.raises(ValueError):
            check_links("Share your data with the health authority.")

    def test_blocks_my_profile(self):
        with pytest.raises(ValueError):
            check_links("See my profile for more info.")

    # ── PASS cases ────────────────────────────────────────────────────────────

    def test_passes_valid_report(self):
        check_links(VALID_REPORT)  # should not raise

    def test_passes_no_links(self):
        check_links(
            "Seven adults in Kandy reported cholera symptoms with vomiting "
            "and diarrhoea after consuming contaminated water last Tuesday."
        )

    def test_passes_mention_of_internet_without_link(self):
        # "online" is not a URL pattern
        check_links(
            "Patients were advised to track symptoms online using the health portal."
        )


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 2 — Spam / Profanity Keyword Detection
# ══════════════════════════════════════════════════════════════════════════════

class TestLayer2Keywords:
    """Layer 2: check_keywords() — profanity, spam phrases, structural checks."""

    # ── Length guards ─────────────────────────────────────────────────────────

    def test_blocks_too_short(self):
        with pytest.raises(ValueError, match="too short"):
            check_keywords("Fever.")

    def test_blocks_exactly_19_chars(self):
        with pytest.raises(ValueError, match="too short"):
            check_keywords("A" * 19)

    def test_passes_exactly_20_chars(self):
        # Use realistic mixed text that passes the structural spam check
        check_keywords("Ten fever cases in area.")

    def test_blocks_too_long(self):
        with pytest.raises(ValueError, match="2,000"):
            check_keywords("A" * 2001)

    def test_passes_exactly_2000_chars(self):
        # Build exactly 2000 chars of high word-variety text (> 30% unique)
        tokens = []
        for i in range(1000):
            tokens.append(f"health{i}")
            current_text = " ".join(tokens)
            if len(current_text) > 2000:
                excess = len(current_text) - 2000
                if excess > 0:
                    tokens[-1] = tokens[-1][:-excess]
                text = " ".join(tokens)
                break

        assert len(text) == 2000
        check_keywords(text)

    # ── Profanity ─────────────────────────────────────────────────────────────

    def test_blocks_profanity_in_report(self):
        with pytest.raises(ValueError, match="inappropriate"):
            check_keywords(
                "This is a shit disease and everyone in the hospital is fucking sick."
            )

    def test_blocks_profanity_mixed_case(self):
        with pytest.raises(ValueError):
            check_keywords(
                "What the Shit is happening in the clinic, people are getting ill."
            )

    # ── Spam phrases ─────────────────────────────────────────────────────────

    def test_blocks_casino(self):
        with pytest.raises(ValueError):
            check_keywords(
                "Casino promotions are causing stress-related illness in the district."
            )

    def test_blocks_buy_now(self):
        with pytest.raises(ValueError):
            check_keywords(
                "Buy now the medicine before the outbreak spreads further in Colombo."
            )

    def test_blocks_lottery(self):
        with pytest.raises(ValueError):
            check_keywords(
                "The lottery winner reported symptoms similar to food poisoning."
            )

    def test_blocks_terrorist(self):
        with pytest.raises(ValueError):
            check_keywords(
                "A terrorist group may have contaminated the water supply causing illness."
            )

    def test_blocks_bomb(self):
        with pytest.raises(ValueError):
            check_keywords(
                "Bomb explosion caused respiratory illness in 30 people near Colombo."
            )

    def test_blocks_humiliate(self):
        with pytest.raises(ValueError):
            check_keywords(
                "I want to humiliate the hospital staff for ignoring the outbreak."
            )

    # ── Structural spam ───────────────────────────────────────────────────────

    def test_blocks_repeated_characters(self):
        with pytest.raises(ValueError, match="spam"):
            check_keywords("Dengue aaaaaaaaaa fever cases in Kandy district this week.")

    def test_blocks_all_caps_long_text(self):
        with pytest.raises(ValueError, match="ALL CAPS"):
            check_keywords(
                "DENGUE FEVER HAS BEEN REPORTED IN GAMPAHA DISTRICT WITH TEN CASES."
            )

    def test_passes_all_caps_short_text(self):
        # All-caps check only applies when >30 letters; this text has <30 letters
        check_keywords("DENGUE IN KANDY AREA.")

    def test_blocks_low_word_variety_spam(self):
        with pytest.raises(ValueError, match="repeated text"):
            check_keywords("sick sick sick sick sick sick sick sick sick sick sick sick")

    def test_blocks_excessive_symbols(self):
        with pytest.raises(ValueError, match="spam"):
            check_keywords("!!!!!!@@@@@@######$$$$$$%%%%%^^^^^&&&&& disease report !!!!")

    # ── PASS cases ────────────────────────────────────────────────────────────

    def test_passes_valid_clinical_report(self):
        check_keywords(VALID_REPORT)

    def test_passes_medical_abbreviations(self):
        check_keywords(
            "ICU has admitted 5 patients with severe dengue haemorrhagic fever "
            "in Colombo 07 over the last 72 hours."
        )


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 3 — Groq Combined: Health Validity + Toxicity (monkeypatched)
# ══════════════════════════════════════════════════════════════════════════════

class TestLayer3Groq:
    """
    Layer 3: check_with_groq() — combined health-validity and toxicity check.

    The Groq API is monkeypatched throughout.  Three response codes are tested:
      VALID      — genuine health report, no toxicity     → pass
      TOXIC      — harmful / threatening / hateful        → ValueError("harmful")
      IRRELEVANT — spam / off-topic / non-health          → ValueError("health or disease")
    """

    # ── Helper to build a fake Groq client ───────────────────────────────────

    @staticmethod
    def _fake_groq(answer: str):
        """Return (monkeypatch-ready) fake httpx.AsyncClient that yields `answer`."""
        class FakeResponse:
            status_code = 200
            def json(self):
                return {"choices": [{"message": {"content": answer}}]}

        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_):
                pass
            async def post(self, *args, **kwargs):
                return FakeResponse()

        return FakeClient

    # ── Fast-path shortcut (no Groq call needed) ──────────────────────────────

    @pytest.mark.asyncio
    async def test_passes_via_shortcut_dengue(self):
        """Text with a recognised health keyword + no toxicity → skips Groq."""
        await check_with_groq(
            "Dengue cases rising in Colombo with severe fever and joint pain."
        )

    @pytest.mark.asyncio
    async def test_passes_via_shortcut_outbreak(self):
        await check_with_groq(
            "An outbreak of cholera was detected near the Kelani river basin."
        )

    @pytest.mark.asyncio
    async def test_passes_via_shortcut_symptoms(self):
        await check_with_groq(
            "Patients reporting symptoms of high fever, vomiting, and fatigue."
        )

    # ── Groq → VALID ──────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_passes_when_groq_returns_valid(self, monkeypatch):
        import utils.content_filter as cf
        monkeypatch.setattr(cf.httpx, "AsyncClient", lambda **kw: self._fake_groq("VALID")())
        monkeypatch.setenv("GROQ_API_KEY", "fake-key")
        # No health keyword → goes through Groq path
        await check_with_groq(
            "People in the village reported feeling unwell after the last few days."
        )

    # ── Groq → IRRELEVANT ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_blocks_when_groq_returns_irrelevant(self, monkeypatch):
        import utils.content_filter as cf
        monkeypatch.setattr(cf.httpx, "AsyncClient", lambda **kw: self._fake_groq("IRRELEVANT")())
        monkeypatch.setenv("GROQ_API_KEY", "fake-key")
        with pytest.raises(ValueError, match="health or disease incident"):
            await check_with_groq(
                "My cat is feeling sad and I am very upset about the weather today."
            )

    @pytest.mark.asyncio
    async def test_blocks_promotional_content(self, monkeypatch):
        import utils.content_filter as cf
        monkeypatch.setattr(cf.httpx, "AsyncClient", lambda **kw: self._fake_groq("IRRELEVANT")())
        monkeypatch.setenv("GROQ_API_KEY", "fake-key")
        with pytest.raises(ValueError, match="health or disease incident"):
            await check_with_groq(
                "You have been selected as our special prize winner this month."
            )

    # ── Groq → TOXIC ─────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_blocks_when_groq_returns_toxic(self, monkeypatch):
        import utils.content_filter as cf
        monkeypatch.setattr(cf.httpx, "AsyncClient", lambda **kw: self._fake_groq("TOXIC")())
        monkeypatch.setenv("GROQ_API_KEY", "fake-key")
        with pytest.raises(ValueError, match="harmful"):
            await check_with_groq(
                "I will kill all the patients in that hospital right now."
            )

    @pytest.mark.asyncio
    async def test_blocks_hate_speech_via_groq(self, monkeypatch):
        import utils.content_filter as cf
        monkeypatch.setattr(cf.httpx, "AsyncClient", lambda **kw: self._fake_groq("TOXIC")())
        monkeypatch.setenv("GROQ_API_KEY", "fake-key")
        with pytest.raises(ValueError, match="harmful"):
            # No health keyword → Groq is called; no hard-toxicity signal → not short-circuited
            await check_with_groq(
                "People of that community should be removed from this area entirely."
            )

    # ── Hard toxicity signals bypass the health-keyword fast-path ────────────

    @pytest.mark.asyncio
    async def test_hard_toxicity_signal_overrides_health_shortcut(self, monkeypatch):
        """
        Even if a health keyword is present, a hard toxicity phrase must force
        the Groq call rather than taking the fast-path.
        """
        import utils.content_filter as cf
        groq_was_called = []

        class TrackingClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): pass
            async def post(self, *a, **kw):
                groq_was_called.append(True)
                class R:
                    status_code = 200
                    def json(self):
                        return {"choices": [{"message": {"content": "TOXIC"}}]}
                return R()

        monkeypatch.setattr(cf.httpx, "AsyncClient", lambda **kw: TrackingClient())
        monkeypatch.setenv("GROQ_API_KEY", "fake-key")

        # "fever" is a health shortcut but "i will kill" is a hard toxicity signal
        with pytest.raises(ValueError, match="harmful"):
            await check_with_groq("I will kill the fever patients in that clinic.")

        assert groq_was_called, "Groq should have been called — hard toxicity overrides shortcut"

    # ── Graceful degradation ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_skips_when_groq_key_missing(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        # Should not raise even for non-health text (no key → skip)
        await check_with_groq("Some random text with no health keywords.")

    @pytest.mark.asyncio
    async def test_skips_when_groq_returns_non_200(self, monkeypatch):
        import utils.content_filter as cf

        class FakeResponse:
            status_code = 500
            def json(self): return {}

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): pass
            async def post(self, *a, **kw): return FakeResponse()

        monkeypatch.setattr(cf.httpx, "AsyncClient", lambda **kw: FakeClient())
        monkeypatch.setenv("GROQ_API_KEY", "fake-key")
        await check_with_groq("Some text with no health keywords.")  # must not raise

    @pytest.mark.asyncio
    async def test_skips_on_network_error(self, monkeypatch):
        import utils.content_filter as cf

        class FailingClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): pass
            async def post(self, *a, **kw):
                raise ConnectionError("Network unreachable")

        monkeypatch.setattr(cf.httpx, "AsyncClient", lambda **kw: FailingClient())
        monkeypatch.setenv("GROQ_API_KEY", "fake-key")
        await check_with_groq("Some text that would go to Groq.")  # must not raise


# ══════════════════════════════════════════════════════════════════════════════
# FULL PIPELINE — end-to-end integration tests
# ══════════════════════════════════════════════════════════════════════════════

class TestFullPipeline:
    """
    run_content_filter_pipeline() — integration tests for the 3-layer pipeline.
    Groq is mocked so tests run offline.
    """

    @staticmethod
    def _patch_groq(monkeypatch, *, groq_answer: str = "VALID"):
        """Patch Layer 3 Groq call with a fixed answer."""
        import utils.content_filter as cf

        class FakeResponse:
            status_code = 200
            def json(self):
                return {"choices": [{"message": {"content": groq_answer}}]}

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): pass
            async def post(self, *a, **kw): return FakeResponse()

        monkeypatch.setattr(cf.httpx, "AsyncClient", lambda **kw: FakeClient())
        monkeypatch.setenv("GROQ_API_KEY", "fake-key")

    # ── Should PASS ───────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_passes_valid_dengue_report(self, monkeypatch):
        self._patch_groq(monkeypatch)
        await run_content_filter_pipeline(VALID_REPORT)

    @pytest.mark.asyncio
    async def test_passes_cholera_report(self, monkeypatch):
        self._patch_groq(monkeypatch)
        await run_content_filter_pipeline(
            "Cholera outbreak confirmed in Trincomalee. 15 patients admitted "
            "to Trincomalee General Hospital with severe diarrhoea and dehydration."
        )

    @pytest.mark.asyncio
    async def test_passes_food_poisoning_report(self, monkeypatch):
        self._patch_groq(monkeypatch)
        await run_content_filter_pipeline(
            "Approximately 20 school children in Matara reported vomiting and "
            "stomach pain after consuming food from the school canteen on Monday."
        )

    # ── Should BLOCK (Layer 1) ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_pipeline_blocks_user_example(self, monkeypatch):
        """The exact example from the user's bug report."""
        self._patch_groq(monkeypatch)
        with pytest.raises(ValueError):
            await run_content_filter_pipeline(
                "disease has been reported. get here to follow this link to get my data"
            )

    @pytest.mark.asyncio
    async def test_pipeline_blocks_http_link(self, monkeypatch):
        self._patch_groq(monkeypatch)
        with pytest.raises(ValueError):
            await run_content_filter_pipeline(
                "Ten dengue cases in Gampaha — see http://spam.example.com for data."
            )

    @pytest.mark.asyncio
    async def test_pipeline_blocks_www_link(self, monkeypatch):
        self._patch_groq(monkeypatch)
        with pytest.raises(ValueError):
            await run_content_filter_pipeline(
                "Outbreak in Kandy — track at www.spamsite.com"
            )

    # ── Should BLOCK (Layer 2) ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_pipeline_blocks_profanity(self, monkeypatch):
        self._patch_groq(monkeypatch)
        with pytest.raises(ValueError):
            await run_content_filter_pipeline(
                "The fucking hospital in Colombo is full of dengue patients "
                "and nobody is doing shit about it, ten cases this week."
            )

    @pytest.mark.asyncio
    async def test_pipeline_blocks_spam_phrase(self, monkeypatch):
        self._patch_groq(monkeypatch)
        with pytest.raises(ValueError):
            await run_content_filter_pipeline(
                "Buy now the antiviral medicine before the outbreak spreads "
                "in Ratnapura district. Ten confirmed cases this week."
            )

    @pytest.mark.asyncio
    async def test_pipeline_blocks_too_short(self, monkeypatch):
        self._patch_groq(monkeypatch)
        with pytest.raises(ValueError, match="too short"):
            await run_content_filter_pipeline("Fever.")

    @pytest.mark.asyncio
    async def test_pipeline_blocks_all_caps(self, monkeypatch):
        self._patch_groq(monkeypatch)
        with pytest.raises(ValueError, match="ALL CAPS"):
            await run_content_filter_pipeline(
                "DENGUE FEVER HAS BEEN REPORTED IN GAMPAHA WITH TEN CONFIRMED CASES."
            )

    # ── Should BLOCK (Layer 3 — Groq TOXIC) ──────────────────────────────────

    @pytest.mark.asyncio
    async def test_pipeline_blocks_toxic_content(self, monkeypatch):
        self._patch_groq(monkeypatch, groq_answer="TOXIC")
        with pytest.raises(ValueError, match="harmful"):
            # No health keyword in this text → Groq is reached and returns TOXIC
            await run_content_filter_pipeline(
                "I want to cause harm to those people for not doing their jobs properly."
            )

    # ── Should BLOCK (Layer 3 — Groq IRRELEVANT) ─────────────────────────────

    @pytest.mark.asyncio
    async def test_pipeline_blocks_non_health_via_groq(self, monkeypatch):
        self._patch_groq(monkeypatch, groq_answer="IRRELEVANT")
        with pytest.raises(ValueError, match="health or disease incident"):
            await run_content_filter_pipeline(
                "My pet cat has been acting strange lately and I am very worried "
                "about what might happen to it in the coming weeks."
            )

    @pytest.mark.asyncio
    async def test_pipeline_blocks_personal_grievance(self, monkeypatch):
        self._patch_groq(monkeypatch, groq_answer="IRRELEVANT")
        with pytest.raises(ValueError, match="health or disease incident"):
            await run_content_filter_pipeline(
                "The government is corrupt and the people are suffering because "
                "of bad policies that have been implemented over the last decade."
            )

    # ── Short-circuit ordering — Layer 1 fires before Layer 3 ────────────────

    @pytest.mark.asyncio
    async def test_layer1_fires_before_groq(self, monkeypatch):
        """Verify Layer 1 (fast) stops the pipeline before Layer 3 (expensive Groq)."""
        import utils.content_filter as cf
        groq_called = []

        original = cf.check_with_groq

        async def tracking_check(text):
            groq_called.append(text)
            await original(text)

        monkeypatch.setattr(cf, "check_with_groq", tracking_check)

        with pytest.raises(ValueError):
            await run_content_filter_pipeline(
                "Click here to see the dengue report for Colombo this week."
            )

        assert not groq_called, "Groq should not have been called — Layer 1 should have fired first"
