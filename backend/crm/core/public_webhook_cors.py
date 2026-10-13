"""CORS for public form-post webhooks that live on OTHER domains.

The channel partner landing pages (https://projects.arihantspaces.com/cp-leads-*) post their
form straight from the visitor's browser to /api/channel-partner/leads/webhook. The app-wide
CORS allow-list (CORS_ORIGINS) is for the CRM front-end only, so for these pages the API sent
NO Access-Control-Allow-Origin header: the browser still delivered the form (a plain form
post), the lead was created, but the page's script was not allowed to read the reply and showed
"Webhook error".

These endpoints are already public and protected by a secret token in the URL, so letting a
browser READ the reply from any origin adds no exposure (anyone holding the token can already
POST from anywhere). Only the paths below are affected; every other route keeps the strict
allow-list.
"""

from __future__ import annotations

from typing import Iterable

from starlette.responses import Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

PUBLIC_FORM_WEBHOOK_PATHS = ("/api/channel-partner/leads/webhook",)

_STRIP = {b"access-control-allow-origin", b"access-control-allow-credentials"}


class PublicWebhookCORSMiddleware:
    def __init__(self, app: ASGIApp, paths: Iterable[str] = PUBLIC_FORM_WEBHOOK_PATHS) -> None:
        self.app = app
        self.paths = tuple(paths)

    def _matches(self, scope: Scope) -> bool:
        path = scope.get("path", "")
        return any(path == p or path.startswith(p + "/") for p in self.paths)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._matches(scope):
            await self.app(scope, receive, send)
            return

        if scope["method"] == "OPTIONS":  # preflight (JSON posts / custom headers)
            response = Response(
                status_code=204,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "POST, OPTIONS",
                    "Access-Control-Allow-Headers": "content-type, x-webhook-secret",
                    "Access-Control-Max-Age": "600",
                },
            )
            await response(scope, receive, send)
            return

        async def send_with_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = [(k, v) for k, v in message.get("headers", []) if k.lower() not in _STRIP]
                headers.append((b"access-control-allow-origin", b"*"))  # no credentials are ever involved
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_cors)
