def test_officer_disease_and_settings_endpoints(client):
    list_response = client.get("/officer/diseases")
    assert list_response.status_code == 200
    assert list_response.json()[0]["disease_name"] == "Dengue"

    create_response = client.post(
        "/officer/diseases",
        json={"disease_name": "Chikungunya", "description": "Viral disease"},
    )
    assert create_response.status_code == 201
    disease_id = create_response.json()["disease_id"]

    update_response = client.put(
        f"/officer/diseases/{disease_id}",
        json={"disease_name": "ChikV", "description": "Updated"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["disease_name"] == "ChikV"

    settings_response = client.get("/officer/settings")
    assert settings_response.status_code == 200
    assert settings_response.json()["user_id"] == "officer_user"

    name_response = client.put("/officer/settings/name", json={"name": "Updated Officer"})
    assert name_response.status_code == 200
    assert name_response.json()["success"] is True

    password_response = client.put(
        "/officer/settings/password",
        json={"currentPassword": "old-pass-123", "newPassword": "new-pass-123"},
    )
    assert password_response.status_code == 200
    assert password_response.json()["success"] is True


def test_officer_report_endpoints(client):
    metadata_response = client.get("/officer/reports/metadata")
    assert metadata_response.status_code == 200
    assert metadata_response.json()["diseases"][0]["disease_name"] == "Dengue"

    list_response = client.get("/officer/reports", params={"district_id": 1, "limit": 20, "skip": 0})
    assert list_response.status_code == 200
    assert list_response.json()["total"] >= 1

    create_response = client.post(
        "/officer/reports",
        json={
            "week_number": 21,
            "year": 2026,
            "district_id": 1,
            "disease_id": 1,
            "actual_count": 17,
            "case_count": 13,
        },
    )
    assert create_response.status_code == 201
    assert create_response.json()["actual_count"] == 17

    bulk_response = client.post(
        "/officer/reports/bulk",
        json={
            "week_number": 22,
            "year": 2026,
            "disease_id": 1,
            "entries": [{"district_id": 1, "actual_count": 9}],
        },
    )
    assert bulk_response.status_code == 200
    assert bulk_response.json()["updated"] == 1


def test_officer_analysis_endpoints(client):
    thresholds_response = client.get("/officer/thresholds", params={"district_id": 1, "disease_id": 1})
    assert thresholds_response.status_code == 200
    assert thresholds_response.json()["items"][0]["threshold"] == 20

    history_response = client.get(
        "/officer/reports/history-pattern",
        params={"district_id": 1, "disease_id": 1, "year_from": 2020, "year_to": 2026, "limit": 25},
    )
    assert history_response.status_code == 200
    assert history_response.json()["limit"] == 25


def test_officer_delete_user_report(client, mocker):
    mocker.patch(
        "controllers.officerController.officer_delete_user_report",
        return_value={"success": True, "message": "Report deleted successfully by officer"}
    )
    response = client.delete("/officer/user-reports/dummy_id?district=Colombo")
    assert response.status_code == 200
    assert response.json()["success"] is True


def test_officer_ban_user(client, mocker):
    mocker.patch(
        "controllers.officerController.ban_user",
        return_value={"success": True, "message": "User has been banned successfully"}
    )
    response = client.post("/officer/users/dummy_user_id/ban")
    assert response.status_code == 200
    assert response.json()["success"] is True
