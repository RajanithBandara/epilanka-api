import pytest


@pytest.mark.integration
def test_user_profile_endpoints(client, fake_state):
    sync_response = client.post("/users/sync")
    assert sync_response.status_code == 200
    synced_user = sync_response.json()["user"]
    assert synced_user["appwrite_id"] == "test_appwrite_id"

    me_response = client.get("/users/me")
    assert me_response.status_code == 200
    assert me_response.json()["user"]["email"] == "test@example.com"

    settings_response = client.get("/users/settings/test_appwrite_id")
    assert settings_response.status_code == 200
    assert settings_response.json()["user"]["appwrite_id"] == "test_appwrite_id"

    all_users_response = client.get("/users/getall")
    assert all_users_response.status_code == 200
    assert len(all_users_response.json()["users"]) == 1

    update_response = client.put(
        "/users/profile",
        json={"username": "updated-user", "email": "updated@example.com"},
    )
    assert update_response.status_code == 200
    assert update_response.json() == {"message": "Profile updated"}

    upload_response = client.post(
        "/users/profilepic",
        files={"file": ("avatar.png", b"pngdata", "image/png")},
    )
    assert upload_response.status_code == 200
    assert upload_response.json()["message"] == "Profile picture updated"
    assert fake_state["r2"].uploads

    delete_response = client.delete("/users/profilepic")
    assert delete_response.status_code == 200
    assert delete_response.json() == {"message": "Profile picture deleted"}
    assert fake_state["r2"].deletes


@pytest.mark.integration
@pytest.mark.error_handling
def test_user_endpoint_error_paths(client, seed_user_profile):
    seed_user_profile()
    seed_user_profile(
        {"$id": "other-user", "email": "other@example.com", "name": "Other User", "labels": []},
        username="other-user",
    )

    forbidden_response = client.get("/users/settings/other-user")
    assert forbidden_response.status_code == 403

    conflict_response = client.put("/users/profile", json={"email": "other@example.com"})
    assert conflict_response.status_code == 409

    invalid_upload_response = client.post(
        "/users/profilepic",
        files={"file": ("avatar.txt", b"text", "text/plain")},
    )
    assert invalid_upload_response.status_code == 400
