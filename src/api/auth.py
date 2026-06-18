"""Authentication using real Dify console credentials.

A user logs in with their Dify email + password; we validate them against the
Dify console login endpoint and resolve their workspace role. The result is
stored in a signed session cookie. Roles gate destructive actions (prune).
"""

import os

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

import dify_api

router = APIRouter(prefix="/api/auth", tags=["auth"])

ADMIN_ROLES = {
    r.strip().lower() for r in (os.getenv("ADMIN_ROLES") or "owner,admin").split(",") if r.strip()
}
ADMIN_EMAILS = {
    e.strip().lower() for e in (os.getenv("ADMIN_EMAILS") or "").split(",") if e.strip()
}


class LoginBody(BaseModel):
    email: str
    password: str


async def _resolve_identity(
    client: httpx.AsyncClient, email: str, token: str | None, csrf: str | None
) -> dict:
    """Best-effort lookup of the user's display name and workspace role.

    The Dify console API requires both the Bearer token and the CSRF token
    (set as a cookie at login and echoed back in the X-CSRF-Token header).
    """
    name, role = email, "unknown"
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if csrf:
        headers["X-CSRF-Token"] = csrf
    try:
        profile = await client.get(f"{dify_api.BASE_URL}/account/profile", headers=headers)
        if profile.status_code == 200:
            name = profile.json().get("name") or email
    except Exception:
        pass
    try:
        members = await client.get(
            f"{dify_api.BASE_URL}/workspaces/current/members", headers=headers
        )
        if members.status_code == 200:
            for member in members.json().get("accounts", []):
                if (member.get("email") or "").lower() == email.lower():
                    role = (member.get("role") or role).lower()
                    name = member.get("name") or name
                    break
    except Exception:
        pass
    if email.lower() in ADMIN_EMAILS:
        role = "admin"
    return {"name": name, "role": role}


async def _dify_login(email: str, password: str) -> dict:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"{dify_api.BASE_URL}/login", json={"email": email, "password": password}
        )
        if resp.status_code != 200:
            raise HTTPException(status_code=401, detail="Invalid Dify credentials")
        data = resp.json() if resp.content else {}
        if data.get("result") != "success" and "data" not in data:
            raise HTTPException(status_code=401, detail="Invalid Dify credentials")
        token = (data.get("data") or {}).get("access_token") or resp.cookies.get("access_token")
        csrf = resp.cookies.get("csrf_token")
        identity = await _resolve_identity(client, email, token, csrf)
        return {"email": email, **identity}


@router.post("/login")
async def login(body: LoginBody, request: Request) -> dict:
    user = await _dify_login(body.email.strip(), body.password)
    user["is_admin"] = user["role"] in ADMIN_ROLES or user["email"].lower() in ADMIN_EMAILS
    request.session["user"] = user
    return user


@router.get("/me")
def me(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


@router.post("/logout")
def logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


def require_auth(request: Request) -> dict:
    user = request.session.get("user")
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_admin(request: Request, user: dict = Depends(require_auth)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=403,
            detail="This action requires an admin/owner Dify role.",
        )
    return user
