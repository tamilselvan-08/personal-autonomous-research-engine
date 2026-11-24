import uuid

from sqlalchemy import update

from app.models import ResearchTask, TaskStatus

OBJECTIVE = "Research the top 50 AI startups in India with founders and funding."


def _create(client, **overrides) -> dict:
    payload = {"title": "India AI startups", "objective": OBJECTIVE} | overrides
    r = client.post("/api/v1/tasks", json=payload)
    assert r.status_code == 201, r.text
    return r.json()


def _set_status(db_session, task_id: str, status: TaskStatus) -> None:
    db_session.execute(
        update(ResearchTask).where(ResearchTask.id == uuid.UUID(task_id)).values(status=status)
    )
    db_session.commit()


def test_create_task_defaults_to_draft(auth_client) -> None:
    task = _create(auth_client, description="  notes  ")
    assert task["status"] == "draft"
    assert task["description"] == "notes"
    assert task["is_editable"] is True
    assert task["is_deletable"] is True
    assert task["project"] is None


def test_create_with_project(auth_client) -> None:
    project = auth_client.post("/api/v1/projects", json={"name": "P"}).json()
    task = _create(auth_client, project_id=project["id"])
    assert task["project"] == {"id": project["id"], "name": "P"}


def test_create_validation_errors(auth_client) -> None:
    r = auth_client.post("/api/v1/tasks", json={"title": "", "objective": "short"})
    assert r.status_code == 422
    fields = {f["loc"][-1] for f in r.json()["error"]["details"]["fields"]}
    assert {"title", "objective"} <= fields

    r = auth_client.post("/api/v1/tasks", json={"title": "   ", "objective": OBJECTIVE})
    assert r.status_code == 422

    r = auth_client.post("/api/v1/tasks", json={"title": "x" * 201, "objective": OBJECTIVE})
    assert r.status_code == 422


def test_cannot_use_another_users_project(auth_client, other_client) -> None:
    project = other_client.post("/api/v1/projects", json={"name": "Theirs"}).json()
    r = auth_client.post(
        "/api/v1/tasks", json={"title": "T", "objective": OBJECTIVE, "project_id": project["id"]}
    )
    assert r.status_code == 422
    assert r.json()["error"]["details"]["fields"][0]["loc"] == ["body", "project_id"]


def test_client_cannot_set_status(auth_client) -> None:
    task = _create(auth_client, status="running")
    assert task["status"] == "draft"
    r = auth_client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "completed"})
    assert r.status_code == 200
    assert r.json()["status"] == "draft"


def test_list_search_filter_sort_paginate(auth_client, db_session) -> None:
    a = _create(auth_client, title="Alpha fintech", objective="Find fintech companies in Pune")
    b = _create(auth_client, title="Beta climate", objective="List climate startups in Europe")
    c = _create(auth_client, title="Gamma 100% match", objective="Objective with percent sign")
    _set_status(db_session, b["id"], TaskStatus.COMPLETED)

    everything = auth_client.get("/api/v1/tasks").json()
    assert everything["total"] == 3
    # Most recently updated first: b was updated last.
    assert everything["items"][0]["id"] == b["id"]

    by_text = auth_client.get("/api/v1/tasks", params={"q": "pune"}).json()
    assert [t["id"] for t in by_text["items"]] == [a["id"]]

    # LIKE wildcards in the search term are treated literally.
    pct = auth_client.get("/api/v1/tasks", params={"q": "100%"}).json()
    assert [t["id"] for t in pct["items"]] == [c["id"]]
    assert auth_client.get("/api/v1/tasks", params={"q": "_"}).json()["total"] == 0

    completed = auth_client.get("/api/v1/tasks", params={"status": "completed"}).json()
    assert [t["id"] for t in completed["items"]] == [b["id"]]

    multi = auth_client.get("/api/v1/tasks", params=[("status", "completed"), ("status", "draft")])
    assert multi.json()["total"] == 3

    titles = auth_client.get("/api/v1/tasks", params={"sort": "title_asc"}).json()["items"]
    assert [t["title"] for t in titles] == ["Alpha fintech", "Beta climate", "Gamma 100% match"]

    page = auth_client.get("/api/v1/tasks", params={"page": 2, "page_size": 2}).json()
    assert page["pages"] == 2
    assert len(page["items"]) == 1

    assert auth_client.get("/api/v1/tasks", params={"status": "bogus"}).status_code == 422


def test_filter_by_project(auth_client) -> None:
    project = auth_client.post("/api/v1/projects", json={"name": "P"}).json()
    inside = _create(auth_client, project_id=project["id"])
    _create(auth_client)
    r = auth_client.get("/api/v1/tasks", params={"project_id": project["id"]}).json()
    assert [t["id"] for t in r["items"]] == [inside["id"]]


def test_edit_draft_task(auth_client) -> None:
    project = auth_client.post("/api/v1/projects", json={"name": "P"}).json()
    task = _create(auth_client)
    r = auth_client.patch(
        f"/api/v1/tasks/{task['id']}",
        json={"title": "Renamed", "project_id": project["id"]},
    )
    assert r.status_code == 200
    assert r.json()["title"] == "Renamed"
    assert r.json()["objective"] == OBJECTIVE
    assert r.json()["project_id"] == project["id"]

    r = auth_client.patch(f"/api/v1/tasks/{task['id']}", json={"project_id": None})
    assert r.json()["project_id"] is None


def test_edit_rejects_null_title(auth_client) -> None:
    task = _create(auth_client)
    r = auth_client.patch(f"/api/v1/tasks/{task['id']}", json={"title": None})
    assert r.status_code == 422


def test_cannot_edit_non_draft(auth_client, db_session) -> None:
    task = _create(auth_client)
    _set_status(db_session, task["id"], TaskStatus.AWAITING_APPROVAL)
    r = auth_client.patch(f"/api/v1/tasks/{task['id']}", json={"title": "Nope"})
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "TASK_NOT_EDITABLE"
    got = auth_client.get(f"/api/v1/tasks/{task['id']}").json()
    assert got["is_editable"] is False


def test_delete_rules(auth_client, db_session) -> None:
    task = _create(auth_client)
    _set_status(db_session, task["id"], TaskStatus.RUNNING)
    r = auth_client.delete(f"/api/v1/tasks/{task['id']}")
    assert r.status_code == 409
    assert r.json()["error"]["code"] == "TASK_NOT_DELETABLE"

    _set_status(db_session, task["id"], TaskStatus.CANCELLED)
    assert auth_client.delete(f"/api/v1/tasks/{task['id']}").status_code == 204
    assert auth_client.get(f"/api/v1/tasks/{task['id']}").status_code == 404


def test_status_endpoint(auth_client) -> None:
    task = _create(auth_client)
    r = auth_client.get(f"/api/v1/tasks/{task['id']}/status").json()
    assert r["status"] == "draft"
    assert r["allowed_transitions"] == ["planning"]


def test_stats_are_real_counts(auth_client, other_client, db_session) -> None:
    empty = auth_client.get("/api/v1/tasks/stats").json()
    assert empty["total"] == 0 and empty["active"] == 0

    ids = [_create(auth_client)["id"] for _ in range(4)]
    _create(other_client)  # must not be counted
    _set_status(db_session, ids[0], TaskStatus.RUNNING)
    _set_status(db_session, ids[1], TaskStatus.COMPLETED)
    _set_status(db_session, ids[2], TaskStatus.FAILED)

    stats = auth_client.get("/api/v1/tasks/stats").json()
    assert stats["total"] == 4
    assert stats["active"] == 1
    assert stats["completed"] == 1
    assert stats["failed"] == 1
    assert stats["by_status"]["draft"] == 1
    assert set(stats["by_status"]) == {s.value for s in TaskStatus}


def test_recent_activity(auth_client, other_client) -> None:
    task = _create(auth_client)
    auth_client.patch(f"/api/v1/tasks/{task['id']}", json={"title": "Renamed"})
    _create(other_client)
    events = auth_client.get("/api/v1/tasks/recent-activity", params={"limit": 5}).json()
    actions = [e["action"] for e in events]
    assert actions[:2] == ["task.updated", "task.created"]
    assert "user.registered" not in actions
    assert len(events) == 2


def test_cross_user_isolation(auth_client, other_client) -> None:
    task = _create(auth_client)
    tid = task["id"]
    assert other_client.get(f"/api/v1/tasks/{tid}").status_code == 404
    assert other_client.get(f"/api/v1/tasks/{tid}/status").status_code == 404
    assert other_client.patch(f"/api/v1/tasks/{tid}", json={"title": "x"}).status_code == 404
    assert other_client.delete(f"/api/v1/tasks/{tid}").status_code == 404
    assert other_client.get("/api/v1/tasks").json()["total"] == 0


def test_requires_auth(client) -> None:
    assert client.get("/api/v1/tasks").status_code == 401
    assert (
        client.post("/api/v1/tasks", json={"title": "t", "objective": OBJECTIVE}).status_code == 401
    )
