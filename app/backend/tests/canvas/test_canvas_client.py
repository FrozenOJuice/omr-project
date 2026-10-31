import httpx
import pytest
from unittest.mock import AsyncMock
from urllib.parse import parse_qs

from core.token_encryption import TokenCipher, TokenEncryptionError
from integrations import canvas_client as client_module
from integrations.canvas_client import CanvasClient, CanvasRequestError


def canvas_client(handler) -> CanvasClient:
    return CanvasClient(
        api_base_url="http://canvas.internal:6700",
        public_base_url="http://localhost:6700",
        timeout=2,
        transport=httpx.MockTransport(handler),
    )


def test_canvas_tokens_are_encrypted_and_authenticated():
    cipher = TokenCipher("a sufficiently long test secret")
    encrypted = cipher.encrypt("canvas-access-token")

    assert encrypted != "canvas-access-token"
    assert cipher.decrypt(encrypted) == "canvas-access-token"
    with pytest.raises(TokenEncryptionError):
        TokenCipher("another secret").decrypt(encrypted)


@pytest.mark.asyncio
async def test_courses_follow_canvas_pagination_on_the_internal_origin():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.params.get("page") == "2":
            return httpx.Response(200, json=[{"id": 2, "name": "Second"}])
        return httpx.Response(
            200,
            json=[{"id": 1, "name": "First"}],
            headers={
                "Link": '<http://localhost:6700/api/v1/courses?page=2>; rel="next"'
            },
        )

    courses = await canvas_client(handler).get_courses("token")

    assert [course["id"] for course in courses] == [1, 2]
    assert requests[1].url.host == "canvas.internal"
    assert requests[0].url.params.get("include[]") == "term"
    assert all(request.headers["Authorization"] == "Bearer token" for request in requests)


@pytest.mark.asyncio
async def test_students_come_from_the_active_course_user_roster():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[{"id": 3, "email": "student@example.com"}])

    students = await canvas_client(handler).get_students("token", "42")

    assert students[0]["id"] == 3
    assert requests[0].url.path == "/api/v1/courses/42/users"
    assert requests[0].url.params.get("enrollment_type[]") == "student"
    assert requests[0].url.params.get("enrollment_state[]") == "active"
    assert requests[0].headers["Accept"] == "application/json+canvas-string-ids"


@pytest.mark.asyncio
async def test_assignments_are_loaded_in_due_date_order():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=[{"id": 7, "name": "Midterm"}])

    assignments = await canvas_client(handler).get_assignments("token", "42")

    assert assignments[0]["id"] == 7
    assert requests[0].url.path == "/api/v1/courses/42/assignments"
    assert requests[0].url.params.get("order_by") == "due_at"


@pytest.mark.asyncio
async def test_grade_is_sent_as_a_posted_percentage():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"score": 40})

    await canvas_client(handler).update_grade("token", "42", "7", "3", "80%")

    assert requests[0].method == "PUT"
    assert requests[0].url.path == "/api/v1/courses/42/assignments/7/submissions/3"
    assert requests[0].content == b"submission%5Bposted_grade%5D=80%25"


@pytest.mark.asyncio
async def test_grade_can_include_an_individual_submission_comment():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"score": 40})

    await canvas_client(handler).update_grade(
        "token",
        "42",
        "7",
        "3",
        "80%",
        comment="View your marked result: https://omr.example.edu/canvas/results#token=abc",
    )

    form = parse_qs(requests[0].content.decode())
    assert form == {
        "submission[posted_grade]": ["80%"],
        "comment[text_comment]": [
            "View your marked result: https://omr.example.edu/canvas/results#token=abc"
        ],
        "comment[group_comment]": ["false"],
    }


@pytest.mark.asyncio
async def test_canvas_request_paths_preserve_ids_above_javascript_safe_integer():
    large_id = "9007199254740993"
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"id": large_id})

    await canvas_client(handler).update_grade(
        "token", large_id, large_id, large_id, "80%"
    )

    assert requests[0].url.path == (
        f"/api/v1/courses/{large_id}/assignments/{large_id}"
        f"/submissions/{large_id}"
    )
    assert requests[0].headers["Accept"] == "application/json+canvas-string-ids"


@pytest.mark.asyncio
async def test_pagination_rejects_links_to_another_host():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=[],
            headers={"Link": '<https://example.com/courses?page=2>; rel="next"'},
        )

    with pytest.raises(CanvasRequestError, match="unsafe pagination"):
        await canvas_client(handler).get_courses("token")


@pytest.mark.asyncio
async def test_canvas_retries_throttled_idempotent_requests(monkeypatch):
    requests = []
    sleep = AsyncMock()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "2"})
        return httpx.Response(200, json=[])

    monkeypatch.setattr(client_module.asyncio, "sleep", sleep)

    assert await canvas_client(handler).get_courses("token") == []
    assert len(requests) == 2
    sleep.assert_awaited_once_with(2.0)


@pytest.mark.asyncio
async def test_canvas_does_not_retry_before_a_long_retry_after(monkeypatch):
    requests = []
    sleep = AsyncMock()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(429, headers={"Retry-After": "120"})

    monkeypatch.setattr(client_module.asyncio, "sleep", sleep)

    with pytest.raises(CanvasRequestError) as error:
        await canvas_client(handler).get_courses("token")

    assert error.value.status_code == 429
    assert len(requests) == 1
    sleep.assert_not_awaited()


@pytest.mark.asyncio
async def test_invalid_retry_after_uses_bounded_backoff(monkeypatch):
    requests = []
    sleep = AsyncMock()

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if len(requests) == 1:
            return httpx.Response(429, headers={"Retry-After": "not-a-date"})
        return httpx.Response(200, json=[])

    monkeypatch.setattr(client_module.asyncio, "sleep", sleep)

    assert await canvas_client(handler).get_courses("token") == []
    sleep.assert_awaited_once_with(0.5)


@pytest.mark.asyncio
async def test_canvas_rejects_repeated_pagination_urls():
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json=[],
            headers={
                "Link": '<http://canvas.internal:6700/api/v1/courses>; rel="next"'
            },
        )

    with pytest.raises(CanvasRequestError, match="repeated a page"):
        await canvas_client(handler).get_courses("token")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_canvas_rejects_excessive_pagination(monkeypatch):
    monkeypatch.setattr(client_module, "MAX_PAGES", 2)

    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        return httpx.Response(
            200,
            json=[],
            headers={
                "Link": (
                    "<http://canvas.internal:6700/api/v1/courses"
                    f"?page={page + 1}>; rel=\"next\""
                )
            },
        )

    with pytest.raises(CanvasRequestError, match="page limit"):
        await canvas_client(handler).get_courses("token")


@pytest.mark.asyncio
async def test_canvas_errors_do_not_expose_response_bodies():
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "invalid token"})

    with pytest.raises(CanvasRequestError) as error:
        await canvas_client(handler).get_profile("token")

    assert error.value.status_code == 401
    assert str(error.value) == "invalid token"
