from test_workspaces import client, create, grant

from backend import bitrix, store, workspaces


def test_master_reuses_private_webhook_across_objects(client, monkeypatch):
    grant(client, "9001")
    grant(client, "9002")
    master = {"X-Preview-User": "9001"}
    another = {"X-Preview-User": "9002"}
    url = "https://example.bitrix24.by/rest/1/testKey/"
    endpoint = "/api/profile/disk-webhooks"
    created = client.post(endpoint, headers=master, json={"name": "Рабочий портал", "url": url})
    assert created.status_code == 200, created.text
    saved = created.json()
    assert set(saved) == {"id", "name", "portal"}
    assert url not in created.text
    repeated = client.post(endpoint, headers=master, json={"url": url.rstrip("/")})
    assert repeated.json() == saved
    assert client.get(endpoint, headers=master).json() == [saved]
    assert client.get(endpoint, headers=another).json() == []
    assert client.get(endpoint).status_code == 403
    assert not any(key.startswith("profile_disk_webhook:") for key in workspaces.shared())

    seen = []

    async def resolve(public_url, webhook, existing_id):
        seen.append(webhook)
        return 123

    monkeypatch.setattr(bitrix, "resolve_public_file", resolve)
    body = {
        "webhook_id": saved["id"],
        "public_url": "https://example.invalid/workbook",
    }
    projects = [create(client, "9001", sample=False) for _ in range(2)]
    for ident in projects:
        headers = {**master, "X-Project-Id": ident}
        result = client.post("/api/bitrix/connection", headers=headers, json=body)
        assert result.status_code == 200, result.text
        assert result.json()["webhook_profile_id"] == saved["id"]
        assert url not in result.text
    assert seen == [url, url]
    foreign = create(client, "9002", sample=False)
    blocked = client.post(
        "/api/bitrix/connection", headers={**another, "X-Project-Id": foreign}, json=body
    )
    assert blocked.status_code == 404
    assert len(seen) == 2
    assert (
        client.post(endpoint, headers=another, json={"project_id": projects[0]}).status_code == 403
    )

    copied = client.post(endpoint, headers=master, json={"project_id": projects[0]})
    assert copied.json() == saved
    assert (
        client.post(
            "/api/object/table/detach", headers={**master, "X-Project-Id": projects[0]}, json={}
        ).status_code
        == 200
    )
    assert client.get(endpoint, headers=master).json() == [saved]
    object_two = workspaces.project(workspaces.user("9001"), projects[1])
    with store.connect(object_two["db_path"]) as db:
        assert store.setting(db, "webhook") == url


def test_webhook_edit_delete_are_owner_scoped(client):
    from backend import profile_webhooks

    grant(client, "9001")
    grant(client, "9002")
    owner = {"X-Preview-User": "9001"}
    other = {"X-Preview-User": "9002"}
    endpoint = "/api/profile/disk-webhooks"
    original_url = "https://example.bitrix24.by/rest/1/original/"
    replacement = "https://example.bitrix24.by/rest/1/replacement/"
    saved = client.post(
        endpoint, headers=owner, json={"name": "Портал", "url": original_url}
    ).json()
    edit = endpoint + "/" + saved["id"] + "/update"
    delete = endpoint + "/" + saved["id"] + "/delete"
    assert client.post(edit, headers=other, json={"name": "Чужой"}).status_code == 404
    assert client.post(delete, headers=other, json={}).status_code == 404
    assert client.post(edit, json={"name": "Админ"}).status_code == 403
    renamed = client.post(edit, headers=owner, json={"name": "Новое название", "url": ""})
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Новое название"
    assert profile_webhooks.webhook_url("9001", saved["id"]) == original_url
    invalid = client.post(edit, headers=owner, json={"name": "Имя", "url": "invalid"})
    assert invalid.status_code == 422
    assert profile_webhooks.webhook_url("9001", saved["id"]) == original_url
    updated = client.post(edit, headers=owner, json={"name": "Новый ключ", "url": replacement})
    assert updated.json()["id"] == saved["id"]
    assert replacement not in updated.text
    assert profile_webhooks.webhook_url("9001", saved["id"]) == replacement
    repeated = client.post(endpoint, headers=owner, json={"url": replacement})
    assert repeated.json() == updated.json()
    duplicate = client.post(endpoint, headers=owner, json={"url": original_url}).json()
    assert client.post(edit, headers=owner, json={"url": original_url}).status_code == 409
    assert client.post(delete, headers=owner, json={}).status_code == 200
    assert client.post(delete, headers=owner, json={}).status_code == 404
    assert client.get(endpoint, headers=owner).json() == [duplicate]
