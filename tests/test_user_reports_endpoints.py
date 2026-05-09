def test_user_reports_update(client, mocker):
    mocker.patch(
        "controllers.user_reportController.update_user_report",
        return_value={"success": True, "message": "Report updated successfully"}
    )
    response = client.put(
        "/user_reports/update?reportid=dummy_id&location=Colombo",
        json={"description": "Updated description"}
    )
    assert response.status_code == 200
    assert response.json()["success"] is True

def test_user_reports_delete(client, mocker):
    mocker.patch(
        "controllers.user_reportController.delete_user_report",
        return_value={"success": True, "message": "Report deleted successfully"}
    )
    response = client.delete("/user_reports/delete?reportid=dummy_id&location=Colombo")
    assert response.status_code == 200
    assert response.json()["success"] is True
