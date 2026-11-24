import uuid


def _create(client, name: str = "Market maps", description: str | None = "Client work") -> dict:
    r = client.post("/api/v1/projects", json={"name": name, "description": description})
    assert r.status_code == 201, r.text
    return r.json()


def test_project_crud(auth_client) -> None:
    project = _create(auth_client)
    assert project["task_count"] == 0

    got = auth_client.get(f"/api/v1/projects/{project['id']}")
    assert got.status_code == 200
    assert got.json()["name"] == "Market maps"

    patched = auth_client.patch(
        f"/api/v1/projects/{project['id']}", json={"name": "  India AI  ", "description": ""}
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "India AI"
    assert patched.json()["description"] is None

    assert auth_client.delete(f"/api/v1/projects/{project['id']}").status_code == 204
    assert auth_client.get(f"/api/v1/projects/{project['id']}").status_code == 404


def test_project_name_unique_case_insensitive(auth_client) -> None:
    _create(auth_client, "Alpha")
    r = auth_client.post("/api/v1/projects", json={"name": "ALPHA"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "PROJECT_NAME_TAKEN"

    beta = _create(auth_client, "Beta")
    r = auth_client.patch(f"/api/v1/projects/{beta['id']}", json={"name": "alpha"})
    assert r.status_code == 409


def test_same_name_allowed_for_different_users(auth_client, other_client) -> None:
    _create(auth_client, "Shared name")
    _create(other_client, "Shared name")


def test_list_pagination_search_and_counts(auth_client) -> None:
    for i in range(5):
        _create(auth_client, f"Project {i}")
    p0 = auth_client.get("/api/v1/projects").json()["items"][0]
    auth_client.post(
        "/api/v1/tasks",
        json={"title": "T", "objective": "Find ten things about X", "project_id": p0["id"]},
    )
    page = auth_client.get("/api/v1/projects", params={"page": 2, "page_size": 2}).json()
    assert page["total"] == 5
    assert page["pages"] == 3
    assert len(page["items"]) == 2

    first = auth_client.get("/api/v1/projects", params={"page_size": 1}).json()["items"][0]
    assert first["task_count"] == 1

    searched = auth_client.get("/api/v1/projects", params={"q": "project 3"}).json()
    assert [p["name"] for p in searched["items"]] == ["Project 3"]


def test_invalid_pagination_returns_422(auth_client) -> None:
    assert auth_client.get("/api/v1/projects", params={"page": 0}).status_code == 422
    assert auth_client.get("/api/v1/projects", params={"page_size": 101}).status_code == 422


def test_delete_project_with_tasks_requires_detach(auth_client) -> None:
    project = _create(auth_client)
    task = auth_client.post(
        "/api/v1/tasks",
        json={"title": "T", "objective": "Collect AI startups", "project_id": project["id"]},
    ).json()

    r = auth_client.delete(f"/api/v1/projects/{project['id']}")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "PROJECT_HAS_TASKS"
    assert r.json()["error"]["details"]["task_count"] == 1

    r = auth_client.delete(f"/api/v1/projects/{project['id']}", params={"detach_tasks": True})
    assert r.status_code == 204
    t = auth_client.get(f"/api/v1/tasks/{task['id']}").json()
    assert t["project_id"] is None


def test_cross_user_access_is_404(auth_client, other_client) -> None:
    project = _create(auth_client)
    pid = project["id"]
    assert other_client.get(f"/api/v1/projects/{pid}").status_code == 404
    assert other_client.patch(f"/api/v1/projects/{pid}", json={"name": "x"}).status_code == 404
    assert other_client.delete(f"/api/v1/projects/{pid}").status_code == 404
    assert other_client.get("/api/v1/projects").json()["total"] == 0


def test_unknown_project_404_and_bad_uuid_422(auth_client) -> None:
    assert auth_client.get(f"/api/v1/projects/{uuid.uuid4()}").status_code == 404
    assert auth_client.get("/api/v1/projects/not-a-uuid").status_code == 422


def test_project_validation(auth_client) -> None:
    assert auth_client.post("/api/v1/projects", json={"name": "   "}).status_code == 422
    assert auth_client.post("/api/v1/projects", json={"name": "x" * 121}).status_code == 422
    assert (
        auth_client.post(
            "/api/v1/projects", json={"name": "ok", "description": "d" * 2001}
        ).status_code
        == 422
    )
