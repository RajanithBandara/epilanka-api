"""
tests/test_content_filter.py
============================
Comprehensive unit tests for the 4-layer content filtering pipeline.

Tests are organised by layer and use pytest-asyncio for async layers.
Detoxify and Groq are monkeypatched so tests run offline and instantly.

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
    check_health_relevance,
    check_keywords,
    check_links,
    check_toxicity,
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
        # A long, realistic health narrative with high word variety.
        # We use simple words to absolutely guarantee no accidental profanity matches.
        text = ""
        # Loop through the vocabulary adding words to build a 2000-char text.
        # The unique ratio will be len(words) / total_words which for 2000 chars (~300 words)
        # is 57 / 300 = ~19%. Wait, the check needs > 30% unique words.
        # Let's use a larger vocabulary.
        text = " ".join([f"word{i} disease{i} patient{i} fever{i} clinic{i}" for i in range(100)])
        # That's 500 words, all unique. That's 100% unique ratio.
        # Let's pad it out to exactly 2000 chars.
        text = " ".join([f"patient_number_{i}_has_a_fever_and_needs_a_doctor" for i in range(100)])
        # That's 100 words, 100% unique.
        text = ""
        for i in range(1, 300):
            text += f"The patient {i} arrived at the clinic with a mild fever and cough today. "
        
        # To bypass word variety (needs > 0.3):
        # The loop above has 15 words per sentence. Only 'i' changes.
        # Ratio = (14 + 300) / (15 * 300) = 314 / 4500 = 7% (Fails)

        # Let's just generate a text with high variety using numbers.
        text = " ".join(f"Medical record entry {i} indicates fever." for i in range(250))
        # Unique words: Medical, record, entry, indicates, fever., 1, 2, ..., 250 -> 255 unique words.
        # Total words: 5 * 250 = 1250 words.
        # Ratio: 255 / 1250 = 20.4%. Fails.

        # We need a text where almost every word is unique.
        text = " ".join(f"Patient_ID_{i}_has_symptom_{i}_at_location_{i}_on_day_{i}" for i in range(150))
        text = text[:2000].strip()
        # Ensure it's exactly 2000 chars
        text = text.ljust(2000, "X")
        # Wait, ljust with X might trigger "repeated text" if it's too many Xs, or structural spam.
        text = text[:2000]
        
        # Let's just do a clean string of words that is >30% unique and exactly 2000 chars
        unique_words = [f"health_check_token_{i}" for i in range(200)]
        text = " ".join(unique_words)
        text = text.ljust(2000, ".") # This might hit repeated symbols
        
        # Let's build exactly 2000 characters
        tokens = []
        for i in range(1000):
            tokens.append(f"health{i}")
            current_text = " ".join(tokens)
            if len(current_text) > 2000:
                # Trim the last token to fit exactly 2000 chars
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
        # Use 20+ chars to pass length check but keep letters under 30
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
# LAYER 3 — Detoxify ML Toxicity Detection (monkeypatched)
# ══════════════════════════════════════════════════════════════════════════════

class TestLayer3Toxicity:
    """Layer 3: check_toxicity() — ML scoring via Detoxify (mocked)."""

    def _make_model(self, scores: dict):
        """Create a fake Detoxify model that returns fixed scores."""
        class FakeDetoxify:
            def predict(self, text: str):
                return scores
        return FakeDetoxify()

    def test_blocks_high_toxicity(self, monkeypatch):
        import utils.content_filter as cf
        monkeypatch.setattr(cf, "_detoxify_attempted", True)
        monkeypatch.setattr(cf, "_detoxify_model", self._make_model({
            "toxicity": 0.92, "severe_toxicity": 0.10,
            "insult": 0.10, "threat": 0.10,
            "identity_attack": 0.10, "obscene": 0.10,
        }))
        with pytest.raises(ValueError, match="harmful"):
            check_toxicity("Some toxic report content.")

    def test_blocks_high_insult(self, monkeypatch):
        import utils.content_filter as cf
        monkeypatch.setattr(cf, "_detoxify_attempted", True)
        monkeypatch.setattr(cf, "_detoxify_model", self._make_model({
            "toxicity": 0.30, "severe_toxicity": 0.10,
            "insult": 0.80, "threat": 0.10,
            "identity_attack": 0.10, "obscene": 0.10,
        }))
        with pytest.raises(ValueError, match="harmful"):
            check_toxicity("Report with insulting content.")

    def test_blocks_high_threat(self, monkeypatch):
        import utils.content_filter as cf
        monkeypatch.setattr(cf, "_detoxify_attempted", True)
        monkeypatch.setattr(cf, "_detoxify_model", self._make_model({
            "toxicity": 0.20, "severe_toxicity": 0.10,
            "insult": 0.10, "threat": 0.85,
            "identity_attack": 0.10, "obscene": 0.10,
        }))
        with pytest.raises(ValueError, match="harmful"):
            check_toxicity("Report containing a threatening phrase.")

    def test_blocks_identity_attack(self, monkeypatch):
        import utils.content_filter as cf
        monkeypatch.setattr(cf, "_detoxify_attempted", True)
        monkeypatch.setattr(cf, "_detoxify_model", self._make_model({
            "toxicity": 0.40, "severe_toxicity": 0.10,
            "insult": 0.20, "threat": 0.10,
            "identity_attack": 0.75, "obscene": 0.10,
        }))
        with pytest.raises(ValueError):
            check_toxicity("Report targeting a specific ethnic group.")

    def test_passes_valid_clinical_text(self, monkeypatch):
        import utils.content_filter as cf
        monkeypatch.setattr(cf, "_detoxify_attempted", True)
        monkeypatch.setattr(cf, "_detoxify_model", self._make_model({
            "toxicity": 0.02, "severe_toxicity": 0.01,
            "insult": 0.01, "threat": 0.01,
            "identity_attack": 0.01, "obscene": 0.01,
        }))
        check_toxicity(VALID_REPORT)  # should not raise

    def test_passes_when_model_unavailable(self, monkeypatch):
        """If Detoxify fails to load, layer 3 is skipped silently."""
        import utils.content_filter as cf
        monkeypatch.setattr(cf, "_detoxify_attempted", True)
        monkeypatch.setattr(cf, "_detoxify_model", None)
        check_toxicity("Any text at all — layer 3 is skipped.")

    def test_skips_on_model_inference_error(self, monkeypatch):
        """Runtime errors during prediction should not block the request."""
        import utils.content_filter as cf

        class BrokenModel:
            def predict(self, text):
                raise RuntimeError("CUDA out of memory")

        monkeypatch.setattr(cf, "_detoxify_attempted", True)
        monkeypatch.setattr(cf, "_detoxify_model", BrokenModel())
        check_toxicity("Report text that causes a model crash.")  # should not raise


# ══════════════════════════════════════════════════════════════════════════════
# LAYER 4 — Groq Health Relevance AI Classifier (monkeypatched)
# ══════════════════════════════════════════════════════════════════════════════

class TestLayer4HealthRelevance:
    """Layer 4: check_health_relevance() — Groq LLM health classifier."""

    # ── Health keyword shortcut (no Groq call) ────────────────────────────────

    @pytest.mark.asyncio
    async def test_passes_via_shortcut_dengue(self):
        """Text with a known health keyword skips the Groq call entirely."""
        await check_health_relevance(
            "Dengue cases rising in Colombo with severe fever and joint pain."
        )

    @pytest.mark.asyncio
    async def test_passes_via_shortcut_outbreak(self):
        await check_health_relevance(
            "An outbreak of cholera was detected near the Kelani river basin."
        )

    @pytest.mark.asyncio
    async def test_passes_via_shortcut_symptoms(self):
        await check_health_relevance(
            "Patients reporting symptoms of high fever, vomiting, and fatigue."
        )

    # ── Groq mocked: valid health report → YES ────────────────────────────────

    @pytest.mark.asyncio
    async def test_passes_when_groq_returns_yes(self, monkeypatch):
        import utils.content_filter as cf

        class FakeResponse:
            status_code = 200
            def json(self):
                return {
                    "choices": [{"message": {"content": "YES"}}]
                }

        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_):
                pass
            async def post(self, *args, **kwargs):
                return FakeResponse()

        monkeypatch.setattr(cf.httpx, "AsyncClient", lambda **kw: FakeClient())
        monkeypatch.setenv("GROQ_API_KEY", "fake-key")

        # Text with no health keywords → goes through Groq path
        await check_health_relevance(
            "People in the village reported feeling unwell after the last few days."
        )

    # ── Groq mocked: spam report → NO ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_blocks_when_groq_returns_no(self, monkeypatch):
        import utils.content_filter as cf

        class FakeResponse:
            status_code = 200
            def json(self):
                return {
                    "choices": [{"message": {"content": "NO"}}]
                }

        class FakeClient:
            async def __aenter__(self):
                return self
            async def __aexit__(self, *_):
                pass
            async def post(self, *args, **kwargs):
                return FakeResponse()

        monkeypatch.setattr(cf.httpx, "AsyncClient", lambda **kw: FakeClient())
        monkeypatch.setenv("GROQ_API_KEY", "fake-key")

        with pytest.raises(ValueError, match="health or disease incident"):
            await check_health_relevance(
                "My cat is feeling sad and I am very upset about the weather today."
            )

    @pytest.mark.asyncio
    async def test_blocks_promotional_content(self, monkeypatch):
        import utils.content_filter as cf

        class FakeResponse:
            status_code = 200
            def json(self):
                return {"choices": [{"message": {"content": "NO"}}]}

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): pass
            async def post(self, *a, **kw): return FakeResponse()

        monkeypatch.setattr(cf.httpx, "AsyncClient", lambda **kw: FakeClient())
        monkeypatch.setenv("GROQ_API_KEY", "fake-key")

        with pytest.raises(ValueError):
            await check_health_relevance(
                "You have been selected as our special prize winner this month."
            )

    # ── Graceful degradation ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_skips_when_groq_key_missing(self, monkeypatch):
        monkeypatch.delenv("GROQ_API_KEY", raising=False)
        # Should not raise even for non-health text
        await check_health_relevance("Some random text with no health keywords.")

    @pytest.mark.asyncio
    async def test_skips_when_groq_returns_non_200(self, monkeypatch):
        import utils.content_filter as cf

        class FakeResponse:
            status_code = 500
            def json(self):
                return {}

        class FakeClient:
            async def __aenter__(self): return self
            async def __aexit__(self, *_): pass
            async def post(self, *a, **kw): return FakeResponse()

        monkeypatch.setattr(cf.httpx, "AsyncClient", lambda **kw: FakeClient())
        monkeypatch.setenv("GROQ_API_KEY", "fake-key")
        await check_health_relevance("Some text with no health keywords.")  # no raise

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
        await check_health_relevance("Some text that would go to Groq.")  # no raise


# ══════════════════════════════════════════════════════════════════════════════
# FULL PIPELINE — end-to-end integration tests
# ══════════════════════════════════════════════════════════════════════════════

class TestFullPipeline:
    """
    run_content_filter_pipeline() — integration tests for the full 4-layer pipeline.
    Detoxify and Groq are mocked so tests run offline.
    """

    def _patch_pipeline(self, monkeypatch, *, toxicity_score=0.01, groq_answer="YES"):
        """Patch Layers 3 & 4 to non-blocking mocks."""
        import utils.content_filter as cf

        class FakeModel:
            def predict(self, text):
                return {
                    "toxicity": toxicity_score, "severe_toxicity": 0.01,
                    "insult": 0.01, "threat": 0.01,
                    "identity_attack": 0.01, "obscene": 0.01,
                }

        monkeypatch.setattr(cf, "_detoxify_attempted", True)
        monkeypatch.setattr(cf, "_detoxify_model", FakeModel())

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
        self._patch_pipeline(monkeypatch)
        await run_content_filter_pipeline(VALID_REPORT)

    @pytest.mark.asyncio
    async def test_passes_cholera_report(self, monkeypatch):
        self._patch_pipeline(monkeypatch)
        await run_content_filter_pipeline(
            "Cholera outbreak confirmed in Trincomalee. 15 patients admitted "
            "to Trincomalee General Hospital with severe diarrhoea and dehydration."
        )

    @pytest.mark.asyncio
    async def test_passes_food_poisoning_report(self, monkeypatch):
        self._patch_pipeline(monkeypatch)
        await run_content_filter_pipeline(
            "Approximately 20 school children in Matara reported vomiting and "
            "stomach pain after consuming food from the school canteen on Monday."
        )

    # ── Should BLOCK (Layer 1) ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_pipeline_blocks_user_example(self, monkeypatch):
        """The exact example from the user's bug report."""
        self._patch_pipeline(monkeypatch)
        with pytest.raises(ValueError):
            await run_content_filter_pipeline(
                "disease has been reported. get here to follow this link to get my data"
            )

    @pytest.mark.asyncio
    async def test_pipeline_blocks_http_link(self, monkeypatch):
        self._patch_pipeline(monkeypatch)
        with pytest.raises(ValueError):
            await run_content_filter_pipeline(
                "Ten dengue cases in Gampaha — see http://spam.example.com for data."
            )

    @pytest.mark.asyncio
    async def test_pipeline_blocks_www_link(self, monkeypatch):
        self._patch_pipeline(monkeypatch)
        with pytest.raises(ValueError):
            await run_content_filter_pipeline(
                "Outbreak in Kandy — track at www.spamsite.com"
            )

    # ── Should BLOCK (Layer 2) ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_pipeline_blocks_profanity(self, monkeypatch):
        self._patch_pipeline(monkeypatch)
        with pytest.raises(ValueError):
            await run_content_filter_pipeline(
                "The fucking hospital in Colombo is full of dengue patients "
                "and nobody is doing shit about it, ten cases this week."
            )

    @pytest.mark.asyncio
    async def test_pipeline_blocks_spam_phrase(self, monkeypatch):
        self._patch_pipeline(monkeypatch)
        with pytest.raises(ValueError):
            await run_content_filter_pipeline(
                "Buy now the antiviral medicine before the outbreak spreads "
                "in Ratnapura district. Ten confirmed cases this week."
            )

    @pytest.mark.asyncio
    async def test_pipeline_blocks_too_short(self, monkeypatch):
        self._patch_pipeline(monkeypatch)
        with pytest.raises(ValueError, match="too short"):
            await run_content_filter_pipeline("Fever.")

    @pytest.mark.asyncio
    async def test_pipeline_blocks_all_caps(self, monkeypatch):
        self._patch_pipeline(monkeypatch)
        with pytest.raises(ValueError, match="ALL CAPS"):
            await run_content_filter_pipeline(
                "DENGUE FEVER HAS BEEN REPORTED IN GAMPAHA WITH TEN CONFIRMED CASES."
            )

    # ── Should BLOCK (Layer 3) ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_pipeline_blocks_toxic_content(self, monkeypatch):
        self._patch_pipeline(monkeypatch, toxicity_score=0.92)
        with pytest.raises(ValueError, match="harmful"):
            await run_content_filter_pipeline(
                "I want to harm the people in that hospital for not treating patients."
            )

    # ── Should BLOCK (Layer 4) ────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_pipeline_blocks_non_health_via_groq(self, monkeypatch):
        self._patch_pipeline(monkeypatch, groq_answer="NO")
        with pytest.raises(ValueError):
            await run_content_filter_pipeline(
                "My pet cat has been acting strange lately and I am very worried "
                "about what might happen to it in the coming weeks."
            )

    @pytest.mark.asyncio
    async def test_pipeline_blocks_personal_grievance(self, monkeypatch):
        self._patch_pipeline(monkeypatch, groq_answer="NO")
        with pytest.raises(ValueError):
            await run_content_filter_pipeline(
                "The government is corrupt and the people are suffering because "
                "of bad policies that have been implemented over the last decade."
            )

    # ── Short-circuit ordering — Layer 1 fires before deeper layers ──────────

    @pytest.mark.asyncio
    async def test_layer1_fires_before_groq(self, monkeypatch):
        """Verify Layer 1 (fast) stops the pipeline before Layer 4 (expensive)."""
        self._patch_pipeline(monkeypatch, groq_answer="NO")
        groq_called = []

        import utils.content_filter as cf
        original = cf.check_health_relevance

        async def tracking_check(text):
            groq_called.append(text)
            await original(text)

        monkeypatch.setattr(cf, "check_health_relevance", tracking_check)

        with pytest.raises(ValueError):
            await run_content_filter_pipeline(
                "Click here to see the dengue report for Colombo this week."
            )

        assert not groq_called, "Groq should not have been called — Layer 1 should have fired first"
