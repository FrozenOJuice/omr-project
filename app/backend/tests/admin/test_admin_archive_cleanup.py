import pytest

from routers import admin_router

pytestmark = pytest.mark.db


async def test_archive_cleanup_requires_explicit_confirmation(
    client,
    admin_headers,
    monkeypatch,
):
    called = False

    async def fake_process(db, storage):
        nonlocal called
        called = True
        return {"scanned_images": 0, "exam_records": 0}

    monkeypatch.setattr(admin_router, "process_due_retention", fake_process)

    response = await client.post(
        "/api/admin/courses/cleanup-archives",
        headers=await admin_headers(),
        json={"confirmed": False},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "archive_cleanup_confirmation_required"
    assert called is False


async def test_archive_cleanup_runs_retention_processor_for_admin(
    client,
    admin_headers,
    monkeypatch,
):
    called = False

    async def fake_process(db, storage):
        nonlocal called
        called = True
        return {"scanned_images": 2, "exam_records": 1}

    monkeypatch.setattr(admin_router, "process_due_retention", fake_process)

    response = await client.post(
        "/api/admin/courses/cleanup-archives",
        headers=await admin_headers(),
        json={"confirmed": True},
    )

    assert response.status_code == 200
    assert response.json() == {"scanned_images": 2, "exam_records": 1}
    assert called is True
