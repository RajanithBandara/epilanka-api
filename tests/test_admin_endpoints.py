def test_admin_account_management_endpoints(client):
    register_response = client.post(
        "/admin/register",
        json={"email": "new-admin@example.com", "password": "secret123", "name": "New Admin"},
    )
    assert register_response.status_code == 201
    new_admin_id = register_response.json()["admin"]["id"]

    list_response = client.get("/admin/list")
    assert list_response.status_code == 200
    assert any(admin["id"] == new_admin_id for admin in list_response.json()["admins"])

    remove_response = client.delete(f"/admin/admins/{new_admin_id}")
    assert remove_response.status_code == 200
    assert remove_response.json()["msg"] == "Admin removed"


def test_admin_officer_management_endpoints(client):
    register_response = client.post(
        "/admin/register-officer",
        json={"email": "new-officer@example.com", "password": "secret123", "name": "New Officer"},
    )
    assert register_response.status_code == 201
    new_officer_id = register_response.json()["officer"]["id"]

    list_response = client.get("/admin/officers")
    assert list_response.status_code == 200
    assert any(officer["id"] == new_officer_id for officer in list_response.json()["officers"])

    remove_response = client.delete(f"/admin/officers/{new_officer_id}")
    assert remove_response.status_code == 200
    assert remove_response.json()["msg"] == "Officer removed"


def test_admin_user_management_endpoints(client, seed_user_profile):
    seed_user_profile()

    list_response = client.get("/admin/users")
    assert list_response.status_code == 200
    assert list_response.json()[0]["appwrite_id"] == "test_appwrite_id"

    ban_response = client.put(
        "/admin/users/test_appwrite_id/ban",
        params={"is_banned": "true", "reason": "Repeated abuse"},
    )
    assert ban_response.status_code == 200

    banned_response = client.get("/admin/users/banned")
    assert banned_response.status_code == 200
    assert banned_response.json()[0]["appwrite_id"] == "test_appwrite_id"

    activity_response = client.get("/admin/users/test_appwrite_id/activity")
    assert activity_response.status_code == 200
    assert activity_response.json()[0]["action"] == "login"

    delete_response = client.delete("/admin/users/test_appwrite_id")
    assert delete_response.status_code == 200
    assert delete_response.json()["msg"] == "User removed"


def test_admin_postgres_endpoints(client):
    tables_response = client.get("/admin/postgres/tables", params={"reports_limit": 5})
    assert tables_response.status_code == 200
    assert tables_response.json()["reports_limit"] == 5

    create_response = client.post(
        "/admin/historical-data",
        json={
            "week_number": 20,
            "year": 2026,
            "district_id": 1,
            "disease_id": 1,
            "case_count": 16,
        },
    )
    assert create_response.status_code == 201
    record_id = create_response.json()["data_id"]

    list_response = client.get("/admin/historical-data", params={"district_id": 1, "limit": 20, "skip": 0})
    assert list_response.status_code == 200
    assert any(record["data_id"] == record_id for record in list_response.json())

    get_response = client.get(f"/admin/historical-data/{record_id}")
    assert get_response.status_code == 200
    assert get_response.json()["case_count"] == 16

    delete_response = client.delete(f"/admin/historical-data/{record_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["msg"].startswith("Record")

    diseases_response = client.get("/admin/diseases")
    assert diseases_response.status_code == 200
    assert diseases_response.json()[0]["disease_name"] == "Dengue"
