def test_report_endpoints(client):
    location_response = client.get(
        "/reports/location",
        params={
            "district_name": "Colombo",
            "province_name": "Western",
            "user_id": "test_appwrite_id",
            "limit": 10,
            "skip": 0,
            "days": 30,
        },
    )
    assert location_response.status_code == 200
    assert location_response.json()["items"][0]["district_name"] == "Colombo"

    historical_response = client.get("/reports/historical-chart", params={"district_name": "Colombo"})
    assert historical_response.status_code == 200
    assert historical_response.json()["series"][0]["cases"] == 12

    metadata_response = client.get("/reports/metadata")
    assert metadata_response.status_code == 200
    assert metadata_response.json()["districts"][0]["district_name"] == "Colombo"

    weekly_create_response = client.post(
        "/reports/weekly-records",
        json={
            "week_number": 19,
            "year": 2026,
            "district_id": 1,
            "disease_id": 1,
            "actual_count": 14,
            "case_count": 11,
        },
    )
    assert weekly_create_response.status_code == 201
    assert weekly_create_response.json()["week_number"] == 19

    weekly_list_response = client.get(
        "/reports/weekly-records",
        params={"district_id": 1, "disease_id": 1, "year": 2026, "limit": 20, "skip": 0},
    )
    assert weekly_list_response.status_code == 200
    assert weekly_list_response.json()["total"] >= 2
