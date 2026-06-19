"""Settings tab: view and edit runtime configuration (admin only).

Values are persisted by :mod:`app_settings` as a JSON overlay over ``.env`` and
re-applied to already-imported modules on save. Secret values are never sent to
the client; the UI only learns whether a secret is set.
"""

import base64

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel

import app_settings
from api.auth import require_admin

router = APIRouter(prefix="/api/settings", tags=["settings"])


class UpdateBody(BaseModel):
    values: dict[str, object]


class TestBody(BaseModel):
    # Optional unsaved overrides to test before saving.
    values: dict[str, object] = {}


def _merged(key: str, overrides: dict[str, object]) -> str:
    """Override value if a non-empty one was provided, else the current value."""
    if key in overrides:
        text = "" if overrides[key] is None else str(overrides[key])
        if text and text != app_settings.SECRET_MASK:
            return text
    return app_settings.effective_value(key)


@router.get("")
def get_settings(user: dict = Depends(require_admin)) -> dict:
    return app_settings.public_settings()


@router.put("")
def put_settings(body: UpdateBody, user: dict = Depends(require_admin)) -> dict:
    app_settings.update(body.values)
    return app_settings.public_settings()


def _test_confluence(o: dict[str, object]) -> dict:
    base = _merged("CONFLUENCE_BASE_URL", o).rstrip("/")
    email = _merged("CONFLUENCE_EMAIL", o)
    token = _merged("CONFLUENCE_API_TOKEN", o)
    page_id = _merged("CONFLUENCE_PAGE_ID", o)
    if not all([base, email, token, page_id]):
        return {"ok": False, "detail": "Missing base URL, email, token or page id."}
    auth = "Basic " + base64.b64encode(f"{email}:{token}".encode()).decode()
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.get(
                f"{base}/api/v2/pages/{page_id}",
                headers={"Authorization": auth, "Accept": "application/json"},
            )
        if resp.status_code == 200:
            return {"ok": True, "detail": f"Reached page \"{resp.json().get('title', page_id)}\"."}
        if resp.status_code in (401, 403):
            return {"ok": False, "detail": "Authentication failed (check email / API token)."}
        if resp.status_code == 404:
            return {"ok": False, "detail": "Page not found (check the tracker page id)."}
        return {"ok": False, "detail": f"Unexpected status {resp.status_code}."}
    except httpx.HTTPError as exc:
        return {"ok": False, "detail": f"Could not reach Confluence: {exc}"}


def _test_dify(o: dict[str, object]) -> dict:
    origin = _merged("DIFY_ORIGIN", o).rstrip("/")
    email = _merged("EMAIL", o)
    password = _merged("PASSWORD", o)
    if not all([origin, email, password]):
        return {"ok": False, "detail": "Missing origin, email or password."}
    try:
        with httpx.Client(timeout=20) as client:
            resp = client.post(
                f"{origin}/console/api/login", json={"email": email, "password": password}
            )
        if resp.status_code == 200:
            data = resp.json() if resp.content else {}
            if data.get("result") == "success" or "data" in data:
                return {"ok": True, "detail": "Logged in to Dify successfully."}
            return {"ok": False, "detail": "Login rejected (check email / password)."}
        if resp.status_code in (401, 403):
            return {"ok": False, "detail": "Authentication failed (check email / password)."}
        return {"ok": False, "detail": f"Unexpected status {resp.status_code}."}
    except httpx.HTTPError as exc:
        return {"ok": False, "detail": f"Could not reach Dify: {exc}"}


@router.post("/test")
def test_settings(body: TestBody, user: dict = Depends(require_admin)) -> dict:
    o = body.values or {}
    return {"confluence": _test_confluence(o), "dify": _test_dify(o)}
