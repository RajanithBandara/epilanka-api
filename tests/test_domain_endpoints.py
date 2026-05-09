def test_disease_endpoints(client):
    create_response = client.post(
        "/diseases/add",
        params={"disease_name": "Malaria", "description": "Vector-borne"},
    )
    assert create_response.status_code == 201
    created = create_response.json()["disease"]
    assert created["disease_name"] == "Malaria"

    list_response = client.get("/diseases/list")
    assert list_response.status_code == 200
    assert len(list_response.json()["diseases"]) >= 2

    update_response = client.post(
        f"/diseases/update/{created['disease_id']}",
        params={"disease_name": "Updated Malaria", "description": "Updated description"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["disease"]["disease_name"] == "Updated Malaria"

    delete_response = client.delete(f"/diseases/delete/{created['disease_id']}")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"message": "Disease deleted successfully"}


def test_map_endpoints(client):
    locations_response = client.get("/map/locations")
    assert locations_response.status_code == 200
    assert "Colombo" in locations_response.json()["locations"]

    nearest_response = client.get("/map/nearestlocation", params={"latitude": 6.9, "longitude": 79.8})
    assert nearest_response.status_code == 200
    assert nearest_response.json()["district_name"] == "Colombo"

    districts_response = client.get("/map/alldistricts", params={"target_date": "2026-05-08"})
    assert districts_response.status_code == 200
    assert districts_response.json()["districts"][0]["risk_level"] == "medium"


def test_user_report_endpoints(client):
    submit_response = client.post(
        "/user_reports/submit",
        json={
            "user_id": "ignored-by-api",
            "description": "Possible dengue cluster reported",
            "latitude": 6.9271,
            "longitude": 79.8612,
        },
    )
    assert submit_response.status_code == 201
    assert submit_response.json()["data"]["user_id"] == "test_appwrite_id"

    vote_response = client.post(
        "/user_reports/vote",
        params={"reportid": "report-1", "userid": "test_appwrite_id", "location": "Colombo"},
    )
    assert vote_response.status_code == 201
    assert vote_response.json()["message"] == "Vote recorded successfully"

    voted_response = client.get(
        "/user_reports/voted",
        params={"reportid": "report-1", "userid": "test_appwrite_id", "location": "Colombo"},
    )
    assert voted_response.status_code == 200
    assert voted_response.json()["data"] is True

    unvote_response = client.post(
        "/user_reports/unvote",
        params={"reportid": "report-1", "userid": "test_appwrite_id", "location": "Colombo"},
    )
    assert unvote_response.status_code == 200
    assert unvote_response.json()["message"] == "Vote removed successfully"
