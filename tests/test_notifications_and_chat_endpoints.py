def test_notification_endpoints(client, fake_state):
    create_response = client.post(
        "/notifications/",
        json={"text": "Threshold exceeded", "severity": "warning", "user_id": "test_appwrite_id"},
    )
    assert create_response.status_code == 201
    notification_id = create_response.json()["notification"]["notification_id"]

    list_response = client.get("/notifications/", params={"skip": 0, "limit": 20, "unread_only": "false"})
    assert list_response.status_code == 200
    assert list_response.json()["total"] == 1

    unread_response = client.get("/notifications/unread/count")
    assert unread_response.status_code == 200
    assert unread_response.json()["unread_count"] == 1

    mark_read_response = client.put(f"/notifications/{notification_id}/read")
    assert mark_read_response.status_code == 200
    assert mark_read_response.json()["message"] == "Notification marked as read"

    update_response = client.put(
        f"/notifications/{notification_id}",
        json={"text": "Threshold normalized", "severity": "success", "metadata": {"district": "Colombo"}},
    )
    assert update_response.status_code == 200
    assert update_response.json()["notification"]["text"] == "Threshold normalized"

    mark_all_response = client.put("/notifications/read-all")
    assert mark_all_response.status_code == 200
    assert mark_all_response.json()["count"] >= 0

    delete_response = client.delete(f"/notifications/{notification_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["message"] == "Notification deleted"

    event_names = [event["event_name"] for event in fake_state["emitted_events"] if event["event_name"] != "unread_count_updated"]
    assert event_names == ["notification", "notification_updated", "notification_deleted"]


def test_chat_endpoints(client):
    create_response = client.post("/chat/history/new")
    assert create_response.status_code == 201
    chat_id = create_response.json()["chatId"]

    list_response = client.get("/chat/history")
    assert list_response.status_code == 200
    assert list_response.json()["chats"][0]["id"] == chat_id

    get_response = client.get(f"/chat/history/{chat_id}")
    assert get_response.status_code == 200
    assert get_response.json()["chat"]["title"] == "New Chat"

    message_response = client.post(
        "/chat/history/message",
        json={"chatId": chat_id, "role": "user", "content": "What is the current risk?"},
    )
    assert message_response.status_code == 200
    assert message_response.json()["message"]["role"] == "user"

    delete_response = client.delete(f"/chat/history/{chat_id}")
    assert delete_response.status_code == 200
    assert delete_response.json()["ok"] is True
