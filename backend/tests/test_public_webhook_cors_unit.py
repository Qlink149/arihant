"""CORS for the channel partner landing-page webhook (browser posts from another domain)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from starlette.middleware.cors import CORSMiddleware
from starlette.testclient import TestClient

from crm.core.public_webhook_cors import PUBLIC_FORM_WEBHOOK_PATHS, PublicWebhookCORSMiddleware

LANDING = "https://projects.arihantspaces.com"
WEBHOOK = "/api/channel-partner/leads/webhook"


def _app() -> FastAPI:
    """Same stack as crm.main: a strict, CRM-only allow-list, with our middleware outermost."""
    app = FastAPI()

    @app.post(WEBHOOK)
    async def webhook():
        return JSONResponse(status_code=201, content={"status": "created"})

    @app.post("/api/leads")
    async def other():
        return {"ok": True}

    app.add_middleware(
        CORSMiddleware, allow_origins=["https://crm.arihant.example"], allow_credentials=True,
        allow_methods=["*"], allow_headers=["*"],
    )
    app.add_middleware(PublicWebhookCORSMiddleware)
    return app


def test_the_landing_page_can_read_the_webhook_reply():
    r = TestClient(_app()).post(WEBHOOK, data={"first_name": "x"}, headers={"Origin": LANDING})
    assert r.status_code == 201 and r.json() == {"status": "created"}  # the reply itself is untouched
    assert r.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in r.headers


def test_error_replies_are_readable_too():
    app = _app()

    @app.post("/api/channel-partner/leads/webhook/err")
    async def err():
        return JSONResponse(status_code=409, content={"duplicate": True})

    r = TestClient(app).post("/api/channel-partner/leads/webhook/err", headers={"Origin": LANDING})
    assert r.status_code == 409 and r.headers["access-control-allow-origin"] == "*"  # a real duplicate message can be shown


def test_preflight_for_a_json_post_is_allowed():
    r = TestClient(_app()).options(
        WEBHOOK,
        headers={"Origin": LANDING, "Access-Control-Request-Method": "POST", "Access-Control-Request-Headers": "content-type"},
    )
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == "*"
    assert "POST" in r.headers["access-control-allow-methods"]
    assert "content-type" in r.headers["access-control-allow-headers"].lower()


def test_an_already_allowed_origin_does_not_end_up_with_credentials_and_a_wildcard():
    r = TestClient(_app()).post(WEBHOOK, headers={"Origin": "https://crm.arihant.example"})
    assert r.headers["access-control-allow-origin"] == "*"
    assert "access-control-allow-credentials" not in r.headers


def test_every_other_route_keeps_the_strict_allow_list():
    c = TestClient(_app())
    r = c.post("/api/leads", headers={"Origin": LANDING})
    assert "access-control-allow-origin" not in r.headers  # landing page origin is NOT allowed elsewhere
    ok = c.post("/api/leads", headers={"Origin": "https://crm.arihant.example"})
    assert ok.headers["access-control-allow-origin"] == "https://crm.arihant.example"
    pre = c.options("/api/leads", headers={"Origin": LANDING, "Access-Control-Request-Method": "POST"})
    assert pre.status_code == 400  # preflight from a stranger is still refused


def test_only_the_webhook_path_is_opened():
    assert PUBLIC_FORM_WEBHOOK_PATHS == ("/api/channel-partner/leads/webhook",)
    c = TestClient(_app())
    assert "access-control-allow-origin" not in c.post("/api/leads", headers={"Origin": LANDING}).headers
    # a look-alike path must not match
    mw = PublicWebhookCORSMiddleware(lambda *a: None)
    assert not mw._matches({"path": "/api/channel-partner/leads/webhook-evil"})
    assert mw._matches({"path": "/api/channel-partner/leads/webhook"})


def test_the_real_app_registers_it():
    from crm.main import app

    names = [m.cls.__name__ for m in app.user_middleware]
    assert "PublicWebhookCORSMiddleware" in names
    assert names.index("PublicWebhookCORSMiddleware") < names.index("CORSMiddleware")  # first = outermost
