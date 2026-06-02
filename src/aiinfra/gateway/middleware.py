"""Gateway correlation-ID middleware.

Binds a `request_id` for the lifetime of each HTTP request: honors an inbound
`X-Request-ID` (so a client or upstream proxy can supply one), otherwise
generates a uuid4. The id is bound into the correlation context — so every log
line the request produces carries it — and echoed back on the response header
so the caller can correlate too.

Pure ASGI (not BaseHTTPMiddleware) on purpose: BaseHTTPMiddleware runs the
downstream app in a separate task, where a contextvar set in dispatch may not
be visible to the route handler. A plain ASGI middleware sets the contextvar in
the same task that runs the endpoint, so the binding propagates reliably.
"""

import uuid

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from aiinfra.observability.context import bind_correlation, reset_correlation

REQUEST_ID_HEADER = "X-Request-ID"
_HEADER_KEY = REQUEST_ID_HEADER.lower().encode()


class CorrelationIdMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        inbound = dict(scope["headers"]).get(_HEADER_KEY)
        request_id = inbound.decode() if inbound else str(uuid.uuid4())
        token = bind_correlation(request_id=request_id)

        async def send_with_header(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            await self.app(scope, receive, send_with_header)
        finally:
            reset_correlation(token)
