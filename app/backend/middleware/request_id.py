import uuid

from fastapi import Request


def get_or_create_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)

    if request_id:
        return request_id

    request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
    request.state.request_id = request_id

    return request_id


async def add_request_id(request: Request, call_next):
    request_id = get_or_create_request_id(request)

    response = await call_next(request)

    response.headers["X-Request-ID"] = request_id

    return response
