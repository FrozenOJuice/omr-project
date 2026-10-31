import asyncio
from collections.abc import Mapping
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any
from urllib.parse import urljoin, urlparse, urlunparse

import httpx


MAX_PAGES = 100
MAX_RETRIES = 3
MAX_RETRY_DELAY_SECONDS = 5.0
MAX_RETRY_AFTER_SECONDS = 60.0
RETRYABLE_METHODS = frozenset({"GET", "PUT", "DELETE"})
RETRYABLE_STATUS_CODES = frozenset({408, 429, 502, 503, 504})


class CanvasRequestError(Exception):
    def __init__(self, message: str, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class CanvasClient:
    def __init__(
        self,
        *,
        api_base_url: str,
        public_base_url: str,
        timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_base_url = api_base_url.rstrip("/") + "/"
        self.public_base_url = public_base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.transport = transport
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> "CanvasClient":
        self._http = httpx.AsyncClient(
            timeout=self.timeout,
            transport=self.transport,
        )
        return self

    async def __aexit__(self, *_args: object) -> None:
        if self._http:
            await self._http.aclose()
            self._http = None

    async def get_profile(self, access_token: str) -> dict[str, Any]:
        result = await self._request(
            "GET", "api/v1/users/self/profile", token=access_token
        )
        return self._object(result)

    async def get_courses(self, access_token: str) -> list[dict[str, Any]]:
        return await self._paginated_get(
            "api/v1/courses",
            access_token,
            params={
                "enrollment_type": "teacher",
                "enrollment_state": "active",
                "state[]": "available",
                "include[]": "term",
                "per_page": 100,
            },
        )

    async def get_students(
        self, access_token: str, course_id: str
    ) -> list[dict[str, Any]]:
        return await self._paginated_get(
            f"api/v1/courses/{course_id}/users",
            access_token,
            params={
                "enrollment_type[]": "student",
                "enrollment_state[]": "active",
                "per_page": 100,
            },
        )

    async def get_assignments(
        self, access_token: str, course_id: str
    ) -> list[dict[str, Any]]:
        return await self._paginated_get(
            f"api/v1/courses/{course_id}/assignments",
            access_token,
            params={"order_by": "due_at", "per_page": 100},
        )

    async def update_grade(
        self,
        access_token: str,
        course_id: str,
        assignment_id: str,
        user_id: str,
        posted_grade: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        data = {"submission[posted_grade]": posted_grade}
        if comment:
            data["comment[text_comment]"] = comment
            data["comment[group_comment]"] = "false"
        result = await self._request(
            "PUT",
            f"api/v1/courses/{course_id}/assignments/{assignment_id}/submissions/{user_id}",
            token=access_token,
            data=data,
        )
        return self._object(result)

    async def _paginated_get(
        self,
        path: str,
        access_token: str,
        *,
        params: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        url = urljoin(self.api_base_url, path)
        items: list[dict[str, Any]] = []
        current_params: Mapping[str, Any] | None = params
        seen_urls: set[str] = set()

        while url:
            if url in seen_urls:
                raise CanvasRequestError("Canvas pagination repeated a page")
            if len(seen_urls) >= MAX_PAGES:
                raise CanvasRequestError("Canvas pagination exceeded the page limit")
            seen_urls.add(url)
            result, next_url = await self._request_page(
                url, access_token, current_params
            )
            if not isinstance(result, list):
                raise CanvasRequestError("Canvas returned an invalid list response")
            items.extend(item for item in result if isinstance(item, dict))
            url = next_url
            current_params = None

        return items

    async def _request_page(
        self,
        url: str,
        access_token: str,
        params: Mapping[str, Any] | None,
    ) -> tuple[Any, str | None]:
        response = await self._send(
            "GET", url, token=access_token, params=params
        )
        next_link = response.links.get("next", {}).get("url")
        return self._json(response), self._pagination_url(next_link)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        data: Mapping[str, str] | None = None,
    ) -> Any:
        response = await self._send(
            method, urljoin(self.api_base_url, path), token=token, data=data
        )
        if response.status_code == 204 or not response.content:
            return None
        return self._json(response)

    async def _send(
        self,
        method: str,
        url: str,
        *,
        token: str | None = None,
        data: Mapping[str, str] | None = None,
        params: Mapping[str, Any] | None = None,
    ) -> httpx.Response:
        headers = {"Accept": "application/json+canvas-string-ids"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        response: httpx.Response | None = None
        for attempt in range(MAX_RETRIES + 1):
            try:
                if self._http:
                    response = await self._http.request(
                        method, url, headers=headers, data=data, params=params
                    )
                else:
                    async with httpx.AsyncClient(
                        timeout=self.timeout, transport=self.transport
                    ) as client:
                        response = await client.request(
                            method, url, headers=headers, data=data, params=params
                        )
            except httpx.RequestError as exc:
                if method not in RETRYABLE_METHODS or attempt == MAX_RETRIES:
                    raise CanvasRequestError("Unable to reach Canvas") from exc
                await asyncio.sleep(_retry_delay(None, attempt))
                continue

            if (
                response.status_code not in RETRYABLE_STATUS_CODES
                or method not in RETRYABLE_METHODS
                or attempt == MAX_RETRIES
            ):
                break
            delay = _retry_delay(response, attempt)
            if delay is None:
                break
            await asyncio.sleep(delay)

        if response is None:
            raise CanvasRequestError("Unable to reach Canvas")

        if response.is_error:
            message = "Canvas rejected the request"
            try:
                error = response.json()
                if isinstance(error, dict):
                    candidate = (
                        error.get("error_description")
                        or error.get("message")
                        or error.get("error")
                    )
                    if isinstance(candidate, str):
                        message = candidate
            except ValueError:
                pass
            raise CanvasRequestError(message, response.status_code)
        return response

    def _pagination_url(self, url: str | None) -> str | None:
        if not url:
            return None
        expected = urlparse(self.api_base_url)
        public = urlparse(self.public_base_url)
        actual = urlparse(url)
        actual_origin = (actual.scheme, actual.netloc)
        if actual_origin not in {
            (expected.scheme, expected.netloc),
            (public.scheme, public.netloc),
        }:
            raise CanvasRequestError("Canvas returned an unsafe pagination URL")
        return urlunparse(
            (
                expected.scheme,
                expected.netloc,
                actual.path,
                actual.params,
                actual.query,
                actual.fragment,
            )
        )

    @staticmethod
    def _json(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise CanvasRequestError("Canvas returned invalid JSON") from exc

    @staticmethod
    def _object(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise CanvasRequestError("Canvas returned an invalid response")
        return value


def normalize_canvas_id(value: Any) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    canvas_id = str(value)
    return (
        canvas_id
        if 0 < len(canvas_id) <= 20
        and canvas_id.isascii()
        and canvas_id.isdigit()
        and canvas_id[0] != "0"
        else None
    )


def _retry_delay(response: httpx.Response | None, attempt: int) -> float | None:
    if response is not None and (retry_after := response.headers.get("Retry-After")):
        try:
            delay = float(retry_after)
        except ValueError:
            try:
                retry_at = parsedate_to_datetime(retry_after)
                if retry_at.tzinfo is None:
                    retry_at = retry_at.replace(tzinfo=timezone.utc)
                delay = (retry_at - datetime.now(timezone.utc)).total_seconds()
            except (TypeError, ValueError):
                delay = None
        if delay is not None:
            delay = max(0, delay)
            return delay if delay <= MAX_RETRY_AFTER_SECONDS else None
    return min(MAX_RETRY_DELAY_SECONDS, 0.5 * (2**attempt))
