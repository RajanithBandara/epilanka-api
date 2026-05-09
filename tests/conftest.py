from __future__ import annotations

# ruff: noqa: E402

import copy
import uuid
from datetime import datetime, timezone
from pathlib import Path
import sys
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import controllers.notificationController as notification_controller
import controllers.userController as user_controller
import main as main_module
import routes.adminRoutes as admin_route
import routes.chatRoute as chat_route
import routes.diseaseRoute as disease_route
import routes.mapRoute as map_route
import routes.notificationRoute as notification_route
import routes.officerRoute as officer_route
import routes.reportRoute as report_route
import routes.userRoute as user_route
import routes.user_reportRoute as user_report_route
from config import postgredb
from models.diseaseModel import Disease
from models.districtModel import District
from models.historydataModel import HistoryData
from utils import auth_deps


FAKE_USER = {
    "$id": "test_appwrite_id",
    "email": "test@example.com",
    "name": "Test User",
    "labels": [],
    "emailVerification": True,
}


class _SimpleMocker:
    def __init__(self):
        self._patchers = []

    def patch(self, target, *args, **kwargs):
        patcher = patch(target, *args, **kwargs)
        mocked = patcher.start()
        self._patchers.append(patcher)
        return mocked

    def stopall(self):
        while self._patchers:
            self._patchers.pop().stop()

FAKE_ADMIN = {
    "$id": "admin_user",
    "email": "admin@example.com",
    "name": "Admin User",
    "labels": ["admin"],
    "emailVerification": True,
}

FAKE_OFFICER = {
    "$id": "officer_user",
    "email": "officer@example.com",
    "name": "Officer User",
    "labels": ["officer"],
    "emailVerification": True,
}


def _result(**kwargs):
    return type("Result", (), kwargs)()


def _matches_query(document: dict, query: dict | None) -> bool:
    if not query:
        return True

    for key, value in query.items():
        if key == "$or":
            if not any(_matches_query(document, clause) for clause in value):
                return False
            continue

        actual = document.get(key)
        if isinstance(value, dict):
            if "$ne" in value and actual == value["$ne"]:
                return False
            continue

        if actual != value:
            return False

    return True


class FakeCursor:
    def __init__(self, documents: list[dict]):
        self._documents = documents

    def sort(self, field: str, direction: int):
        reverse = direction == -1
        self._documents.sort(key=lambda item: item.get(field), reverse=reverse)
        return self

    def skip(self, amount: int):
        self._documents = self._documents[amount:]
        return self

    def limit(self, amount: int):
        self._documents = self._documents[:amount]
        return self

    def __iter__(self):
        return iter(self._documents)


class FakeCollection:
    def __init__(self):
        self._documents: list[dict] = []
        self._counter = 1

    def insert_one(self, document: dict):
        stored = copy.deepcopy(document)
        stored["_id"] = str(self._counter)
        self._counter += 1
        self._documents.append(stored)
        return _result(inserted_id=stored["_id"])

    def find_one(self, query: dict | None):
        for document in self._documents:
            if _matches_query(document, query):
                return copy.deepcopy(document)
        return None

    def find(self, query: dict | None = None, projection: dict | None = None):
        documents = [
            copy.deepcopy(document)
            for document in self._documents
            if _matches_query(document, query)
        ]
        if projection:
            excluded = {key for key, value in projection.items() if value == 0}
            for document in documents:
                for key in excluded:
                    document.pop(key, None)
        return FakeCursor(documents)

    def count_documents(self, query: dict | None = None):
        return sum(1 for document in self._documents if _matches_query(document, query))

    def update_one(self, query: dict, update: dict):
        for document in self._documents:
            if _matches_query(document, query):
                for key, value in update.get("$set", {}).items():
                    document[key] = value
                return _result(matched_count=1, modified_count=1)
        return _result(matched_count=0, modified_count=0)

    def update_many(self, query: dict, update: dict):
        modified = 0
        for document in self._documents:
            if _matches_query(document, query):
                for key, value in update.get("$set", {}).items():
                    document[key] = value
                modified += 1
        return _result(modified_count=modified)

    def delete_one(self, query: dict):
        for index, document in enumerate(self._documents):
            if _matches_query(document, query):
                self._documents.pop(index)
                return _result(deleted_count=1)
        return _result(deleted_count=0)

    def delete_many(self, query: dict):
        kept = []
        deleted = 0
        for document in self._documents:
            if _matches_query(document, query):
                deleted += 1
                continue
            kept.append(document)
        self._documents = kept
        return _result(deleted_count=deleted)


class FakeMongoDatabase:
    def __init__(self):
        self.collections = {
            "users": FakeCollection(),
            "notifications": FakeCollection(),
        }

    def __getitem__(self, item: str):
        return self.collections[item]


class FakeSyncQuery:
    def __init__(self, session: "FakeSyncSession", model):
        self.session = session
        self.model = model
        self.conditions = []
        self._offset = 0
        self._limit = None

    def filter(self, *conditions):
        self.conditions.extend(conditions)
        return self

    def order_by(self, *args, **kwargs):
        return self

    def offset(self, amount: int):
        self._offset = amount
        return self

    def limit(self, amount: int):
        self._limit = amount
        return self

    def first(self):
        records = self.all()
        return records[0] if records else None

    def all(self):
        records = list(self.session.records_for(self.model))
        filtered = [record for record in records if self._matches_all(record)]
        if self._offset:
            filtered = filtered[self._offset:]
        if self._limit is not None:
            filtered = filtered[: self._limit]
        return filtered

    def _matches_all(self, record) -> bool:
        return all(self._matches(record, condition) for condition in self.conditions)

    def _matches(self, record, condition) -> bool:
        left = getattr(condition, "left", None)
        right = getattr(condition, "right", None)
        operator = getattr(condition, "operator", None)
        key = getattr(left, "key", None)
        if key is None:
            return True

        actual = getattr(record, key, None)
        expected = getattr(right, "value", right)
        operator_name = getattr(operator, "__name__", "")

        if operator_name == "eq":
            return str(actual) == str(expected)
        if operator_name == "ne":
            return str(actual) != str(expected)
        if operator_name == "ilike_op":
            normalized = str(expected).replace("%", "").strip().lower()
            return str(actual or "").strip().lower() == normalized

        return True


class FakeSyncSession:
    def __init__(self):
        self.diseases = [
            Disease(disease_id=1, disease_name="Dengue", description="Mosquito-borne"),
        ]
        self.districts = [
            District(
                district_id=1,
                district_name="Colombo",
                latitude=6.9271,
                longitude=79.8612,
                province_name="Western",
            ),
        ]
        self.history = [
            HistoryData(
                data_id=uuid.uuid4(),
                week_number=18,
                year=2026,
                district_id=1,
                disease_id=1,
                case_count=12,
            ),
        ]

    def records_for(self, model):
        if model is Disease:
            return self.diseases
        if model is District:
            return self.districts
        if model is HistoryData:
            return self.history
        return []

    def query(self, model):
        return FakeSyncQuery(self, model)

    def add(self, obj):
        if isinstance(obj, Disease):
            if getattr(obj, "disease_id", None) is None:
                obj.disease_id = max((item.disease_id for item in self.diseases), default=0) + 1
            self.diseases.append(obj)
            return

        if isinstance(obj, HistoryData):
            if getattr(obj, "data_id", None) is None:
                obj.data_id = uuid.uuid4()
            self.history.append(obj)

    def commit(self):
        return None

    def refresh(self, obj):
        return None

    def delete(self, obj):
        if isinstance(obj, Disease):
            self.diseases = [item for item in self.diseases if item.disease_id != obj.disease_id]
            return
        if isinstance(obj, HistoryData):
            self.history = [item for item in self.history if str(item.data_id) != str(obj.data_id)]


class FakeR2Client:
    def __init__(self):
        self.uploads = []
        self.deletes = []

    def upload_fileobj(self, fileobj, bucket, key, ExtraArgs=None):
        self.uploads.append({"bucket": bucket, "key": key, "extra": ExtraArgs or {}})
        return True

    def delete_object(self, Bucket, Key):
        self.deletes.append({"bucket": Bucket, "key": Key})
        return True


@pytest.fixture(scope="session")
def app():
    return main_module.fastapi_app


@pytest.fixture
def mocker():
    helper = _SimpleMocker()
    try:
        yield helper
    finally:
        helper.stopall()


@pytest.fixture
def api_app(app):
    return app.other_asgi_app if hasattr(app, "other_asgi_app") else app


@pytest.fixture
def fake_state():
    return {
        "mongo": FakeMongoDatabase(),
        "sync_db": FakeSyncSession(),
        "async_diseases": [
            {"disease_id": 1, "disease_name": "Dengue", "description": "Mosquito-borne"},
        ],
        "weekly_reports": [
            {
                "id": 1,
                "week_number": 18,
                "year": 2026,
                "district_id": 1,
                "district_name": "Colombo",
                "disease_id": 1,
                "disease_name": "Dengue",
                "actual_count": 12,
                "case_count": 10,
            }
        ],
        "report_votes": set(),
        "chat_store": {},
        "emitted_events": [],
        "r2": FakeR2Client(),
        "admins": [
            {"id": "admin_user", "email": "admin@example.com", "name": "Admin User"},
        ],
        "officers": [
            {"id": "officer_user", "email": "officer@example.com", "name": "Officer User"},
        ],
        "activity_logs": {
            "test_appwrite_id": [{"action": "login", "timestamp": "2026-05-08T09:00:00Z"}],
        },
    }


@pytest.fixture
def seed_user_profile(fake_state):
    def _seed(user: dict | None = None, **overrides):
        source = dict(user or FAKE_USER)
        now = datetime.now(timezone.utc)
        profile = {
            "appwrite_id": source["$id"],
            "username": source["name"],
            "email": source["email"],
            "profile_image": overrides.pop("profile_image", None),
            "created_at": now,
            "updated_at": now,
        }
        profile.update(overrides)
        fake_state["mongo"]["users"].insert_one(profile)
        return profile

    return _seed


@pytest.fixture
def seed_notification(fake_state):
    def _seed(**overrides):
        notification = {
            "notification_id": overrides.pop("notification_id", f"notif_{uuid.uuid4().hex[:8]}"),
            "text": overrides.pop("text", "Test notification"),
            "severity": overrides.pop("severity", "info"),
            "user_id": overrides.pop("user_id", FAKE_USER["$id"]),
            "created_at": overrides.pop("created_at", datetime.now(timezone.utc)),
            "read": overrides.pop("read", False),
            "read_at": overrides.pop("read_at", None),
            "metadata": overrides.pop("metadata", {}),
        }
        notification.update(overrides)
        fake_state["mongo"]["notifications"].insert_one(notification)
        return notification

    return _seed


@pytest.fixture
def client(monkeypatch, app, api_app, fake_state):
    async def _noop_async(*args, **kwargs):
        return None

    def _noop_sync(*args, **kwargs):
        return None

    def _fake_user():
        return dict(FAKE_USER)

    def _fake_admin():
        return dict(FAKE_ADMIN)

    def _fake_officer():
        return dict(FAKE_OFFICER)

    async def _override_async_db():
        yield object()

    def _override_sync_db():
        yield fake_state["sync_db"]

    monkeypatch.setattr(main_module, "connect_to_mongodb", _noop_sync)
    monkeypatch.setattr(main_module, "connect_to_mongodb_async", _noop_sync)
    monkeypatch.setattr(main_module, "close_mongodb_connection", _noop_sync)
    monkeypatch.setattr(main_module, "close_mongodb_async_connection", _noop_async)
    monkeypatch.setattr(main_module, "close_postgres_connection", _noop_async)
    monkeypatch.setattr(main_module, "close_redis_connection", _noop_async)

    monkeypatch.setattr(user_controller, "get_database", lambda: fake_state["mongo"])
    monkeypatch.setattr(notification_controller, "get_database", lambda: fake_state["mongo"])

    monkeypatch.setattr(user_route, "r2_client", fake_state["r2"])
    monkeypatch.setattr(user_route, "BUCKET_NAME", "test-bucket")
    monkeypatch.setattr(user_route, "PUBLIC_BASE_URL", "https://cdn.test")

    async def _emit_to_user(user_id: str, payload: dict, event_name: str = "notification"):
        fake_state["emitted_events"].append(
            {"scope": "user", "user_id": user_id, "event_name": event_name, "payload": payload}
        )

    async def _emit_to_all(payload: dict, exclude_user: str = None, event_name: str = "notification"):
        fake_state["emitted_events"].append(
            {
                "scope": "all",
                "exclude_user": exclude_user,
                "event_name": event_name,
                "payload": payload,
            }
        )

    monkeypatch.setattr(notification_route.notification_manager, "broadcast_to_user", _emit_to_user)
    monkeypatch.setattr(notification_route.notification_manager, "broadcast_to_all", _emit_to_all)

    async def fake_add_disease(db_session, disease_name: str, description: str = None):
        disease = {
            "disease_id": len(fake_state["async_diseases"]) + 1,
            "disease_name": disease_name,
            "description": description,
        }
        fake_state["async_diseases"].append(disease)
        return disease

    async def fake_list_diseases(db_session):
        return fake_state["async_diseases"]

    async def fake_update_disease(db_session, disease_id: int, disease_name: str = None, description: str = None):
        for disease in fake_state["async_diseases"]:
            if disease["disease_id"] == disease_id:
                if disease_name is not None:
                    disease["disease_name"] = disease_name
                if description is not None:
                    disease["description"] = description
                return disease
        return None

    async def fake_delete_disease(db_session, disease_id: int):
        before = len(fake_state["async_diseases"])
        fake_state["async_diseases"] = [
            disease for disease in fake_state["async_diseases"] if disease["disease_id"] != disease_id
        ]
        return len(fake_state["async_diseases"]) != before

    monkeypatch.setattr(disease_route, "add_disease", fake_add_disease)
    monkeypatch.setattr(disease_route, "list_diseases", fake_list_diseases)
    monkeypatch.setattr(disease_route, "update_disease", fake_update_disease)
    monkeypatch.setattr(disease_route, "delete_disease", fake_delete_disease)

    async def fake_get_all_locations():
        return ["Colombo", "Gampaha"]

    async def fake_get_nearest(latitude: float, longitude: float):
        return {"district_name": "Colombo", "latitude": latitude, "longitude": longitude}

    async def fake_get_all_districts(target_date=None):
        return {
            "target_date": str(target_date) if target_date else None,
            "districts": [{"district_id": 1, "district_name": "Colombo", "risk_level": "medium"}],
        }

    monkeypatch.setattr(map_route, "get_all_locations", fake_get_all_locations)
    monkeypatch.setattr(map_route, "fetch_nearest_area_from_postgres_only", fake_get_nearest)
    monkeypatch.setattr(map_route, "fetch_all_districts_map_data", fake_get_all_districts)

    async def fake_process_user_report(payload):
        return {
            "report_id": "report-1",
            "user_id": payload.user_id,
            "description": payload.description,
            "location": {"latitude": payload.latitude, "longitude": payload.longitude},
        }

    async def fake_vote_report(reportid: str, userid: str, location: str):
        fake_state["report_votes"].add((reportid, userid, location))
        return {"reportid": reportid, "votes": len(fake_state["report_votes"])}

    async def fake_unvote_report(reportid: str, userid: str, location: str):
        fake_state["report_votes"].discard((reportid, userid, location))
        return {"reportid": reportid, "votes": len(fake_state["report_votes"])}

    async def fake_has_voted(reportid: str, userid: str, location: str):
        return (reportid, userid, location) in fake_state["report_votes"]

    monkeypatch.setattr(user_report_route, "process_user_report", fake_process_user_report)
    monkeypatch.setattr(user_report_route, "update_report_score", fake_vote_report)
    monkeypatch.setattr(user_report_route, "remove_report_vote", fake_unvote_report)
    monkeypatch.setattr(user_report_route, "has_user_voted", fake_has_voted)

    async def fake_fetch_reports_by_location(**filters):
        return {
            "items": [
                {
                    "report_id": "r-1",
                    "district_name": filters.get("district_name") or "Colombo",
                    "province_name": filters.get("province_name") or "Western",
                }
            ],
            "pagination": {
                "limit": filters["limit"],
                "skip": filters["skip"],
                "days": filters["days"],
            },
        }

    async def fake_fetch_historical_chart_data(district_name: str):
        return {"district_name": district_name, "series": [{"week": 18, "cases": 12}]}

    async def fake_fetch_report_metadata():
        return {
            "districts": [{"district_id": 1, "district_name": "Colombo"}],
            "diseases": [{"disease_id": 1, "disease_name": "Dengue"}],
        }

    async def fake_list_weekly_reports(
        district_id=None,
        disease_id=None,
        week_number=None,
        year=None,
        limit=20,
        skip=0,
    ):
        records = fake_state["weekly_reports"]
        filtered = [
            record
            for record in records
            if (district_id is None or record["district_id"] == district_id)
            and (disease_id is None or record["disease_id"] == disease_id)
            and (week_number is None or record["week_number"] == week_number)
            and (year is None or record["year"] == year)
        ]
        return {"items": filtered[skip : skip + limit], "total": len(filtered)}

    async def fake_create_weekly_report(
        week_number: int,
        year: int,
        district_id: int,
        disease_id: int,
        actual_count: int,
        case_count: int | None = None,
    ):
        record = {
            "id": len(fake_state["weekly_reports"]) + 1,
            "week_number": week_number,
            "year": year,
            "district_id": district_id,
            "district_name": "Colombo",
            "disease_id": disease_id,
            "disease_name": "Dengue",
            "actual_count": actual_count,
            "case_count": case_count,
        }
        fake_state["weekly_reports"].append(record)
        return record

    monkeypatch.setattr(report_route, "fetchReportsbyLocation", fake_fetch_reports_by_location)
    monkeypatch.setattr(report_route, "fetchHistoricalChartData", fake_fetch_historical_chart_data)
    monkeypatch.setattr(report_route, "fetch_report_metadata", fake_fetch_report_metadata)
    monkeypatch.setattr(report_route, "list_weekly_reports", fake_list_weekly_reports)
    monkeypatch.setattr(report_route, "create_weekly_report", fake_create_weekly_report)

    def fake_admin_register(email: str, password: str, name: str):
        admin = {"id": f"admin-{len(fake_state['admins']) + 1}", "email": email, "name": name}
        fake_state["admins"].append(admin)
        return {"msg": "Admin created", "admin": admin}

    def fake_get_all_admins():
        return fake_state["admins"]

    def fake_officer_register(email: str, password: str, name: str):
        officer = {"id": f"officer-{len(fake_state['officers']) + 1}", "email": email, "name": name}
        fake_state["officers"].append(officer)
        return {"msg": "Officer created", "officer": officer}

    def fake_get_all_officers():
        return fake_state["officers"]

    def fake_delete_admin(admin_id: str):
        fake_state["admins"] = [admin for admin in fake_state["admins"] if admin["id"] != admin_id]
        return {"msg": "Admin removed"}

    def fake_delete_officer(officer_id: str):
        fake_state["officers"] = [officer for officer in fake_state["officers"] if officer["id"] != officer_id]
        return {"msg": "Officer removed"}

    def fake_ban_user(user_id: str, is_banned: bool = True, reason: str | None = None):
        for document in fake_state["mongo"]["users"]._documents:
            if document["appwrite_id"] == user_id:
                document["is_banned"] = is_banned
                document["ban_reason"] = reason
                return {"msg": "User updated"}
        return {"msg": "User not found"}

    def fake_view_banned_users():
        return [
            copy.deepcopy(document)
            for document in fake_state["mongo"]["users"]._documents
            if document.get("is_banned")
        ]

    def fake_view_user_activity(user_id: str):
        return fake_state["activity_logs"].get(user_id, [])

    def fake_delete_user(user_id: str):
        before = len(fake_state["mongo"]["users"]._documents)
        fake_state["mongo"]["users"]._documents = [
            document
            for document in fake_state["mongo"]["users"]._documents
            if document["appwrite_id"] != user_id
        ]
        if len(fake_state["mongo"]["users"]._documents) == before:
            return {"msg": "User not found"}
        return {"msg": "User removed"}

    def fake_admin_list_users():
        return [copy.deepcopy(document) for document in fake_state["mongo"]["users"]._documents]

    async def fake_view_tables_postgres(reports_limit: int = 10):
        return {"tables": ["diseases", "historicaldata"], "reports_limit": reports_limit}

    monkeypatch.setattr(admin_route, "admin_register_appwrite", fake_admin_register)
    monkeypatch.setattr(admin_route, "get_all_admins_appwrite", fake_get_all_admins)
    monkeypatch.setattr(admin_route, "officer_register_appwrite", fake_officer_register)
    monkeypatch.setattr(admin_route, "get_all_officers_appwrite", fake_get_all_officers)
    monkeypatch.setattr(admin_route, "delete_admin_appwrite", fake_delete_admin)
    monkeypatch.setattr(admin_route, "delete_officer_appwrite", fake_delete_officer)
    monkeypatch.setattr(admin_route, "ban_users_mongo", fake_ban_user)
    monkeypatch.setattr(admin_route, "view_banned_users_mongo", fake_view_banned_users)
    monkeypatch.setattr(admin_route, "view_user_activity_mongo", fake_view_user_activity)
    monkeypatch.setattr(admin_route, "delete_user_mongo", fake_delete_user)
    monkeypatch.setattr(admin_route, "get_all_users_mongo", fake_admin_list_users)
    monkeypatch.setattr(admin_route, "view_tables_postgres", fake_view_tables_postgres)

    async def fake_fetch_thresholds(district_id=None, disease_id=None):
        return {
            "items": [
                {"district_id": district_id or 1, "disease_id": disease_id or 1, "threshold": 20}
            ]
        }

    async def fake_fetch_history_pattern(
        district_id=None,
        disease_id=None,
        year_from=None,
        year_to=None,
        limit=400,
    ):
        return {
            "items": [
                {
                    "district_id": district_id or 1,
                    "disease_id": disease_id or 1,
                    "year_from": year_from,
                    "year_to": year_to,
                }
            ],
            "limit": limit,
        }

    async def fake_bulk_upsert(week_number: int, year: int, disease_id: int, entries: list[dict]):
        created = []
        for entry in entries:
            created.append(
                await fake_create_weekly_report(
                    week_number=week_number,
                    year=year,
                    district_id=entry["district_id"],
                    disease_id=disease_id,
                    actual_count=entry["actual_count"],
                    case_count=None,
                )
            )
        return {"updated": len(created), "items": created}

    monkeypatch.setattr(officer_route, "fetch_report_metadata", fake_fetch_report_metadata)
    monkeypatch.setattr(officer_route, "list_weekly_reports", fake_list_weekly_reports)
    monkeypatch.setattr(officer_route, "create_weekly_report", fake_create_weekly_report)
    monkeypatch.setattr(officer_route, "fetch_officer_thresholds", fake_fetch_thresholds)
    monkeypatch.setattr(officer_route, "fetch_officer_history_pattern", fake_fetch_history_pattern)
    monkeypatch.setattr(officer_route, "bulk_upsert_weekly_reports", fake_bulk_upsert)

    def fake_create_chat(user_id: str):
        chat_id = f"chat-{len(fake_state['chat_store']) + 1}"
        chat = {
            "id": chat_id,
            "title": "New Chat",
            "messages": [],
            "createdAt": "2026-05-08T09:00:00Z",
            "updatedAt": "2026-05-08T09:00:00Z",
        }
        fake_state["chat_store"][chat_id] = {"user_id": user_id, **chat}
        return {"chatId": chat_id, "chat": chat}

    def fake_list_chats(user_id: str):
        return [
            {key: value for key, value in chat.items() if key != "user_id"}
            for chat in fake_state["chat_store"].values()
            if chat["user_id"] == user_id
        ]

    def fake_get_chat(user_id: str, chat_id: str):
        chat = fake_state["chat_store"].get(chat_id)
        if not chat or chat["user_id"] != user_id:
            return None
        return {key: value for key, value in chat.items() if key != "user_id"}

    def fake_append_message(user_id: str, chat_id: str, role: str, content: str):
        chat = fake_state["chat_store"].get(chat_id)
        if not chat or chat["user_id"] != user_id:
            return None
        message = {"role": role, "content": content, "createdAt": "2026-05-08T09:01:00Z"}
        chat["messages"].append(message)
        chat["updatedAt"] = "2026-05-08T09:01:00Z"
        return message

    def fake_delete_chat(user_id: str, chat_id: str):
        chat = fake_state["chat_store"].get(chat_id)
        if chat and chat["user_id"] == user_id:
            del fake_state["chat_store"][chat_id]
        return True

    monkeypatch.setattr(chat_route, "create_chat", fake_create_chat)
    monkeypatch.setattr(chat_route, "list_chats", fake_list_chats)
    monkeypatch.setattr(chat_route, "get_chat", fake_get_chat)
    monkeypatch.setattr(chat_route, "append_message", fake_append_message)
    monkeypatch.setattr(chat_route, "delete_chat", fake_delete_chat)

    api_app.dependency_overrides[auth_deps.get_current_user] = _fake_user
    api_app.dependency_overrides[auth_deps.get_current_admin] = _fake_admin
    api_app.dependency_overrides[auth_deps.get_current_officer] = _fake_officer
    api_app.dependency_overrides[postgredb.get_async_db] = _override_async_db
    api_app.dependency_overrides[postgredb.get_postgres_connection] = _override_sync_db

    with TestClient(app) as test_client:
        yield test_client

    api_app.dependency_overrides.clear()
