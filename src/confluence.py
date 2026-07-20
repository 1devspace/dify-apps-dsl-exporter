"""Confluence Cloud REST v2 client and storage-format helpers.

Used by the automated tracker sync. Unlike the interactive MCP tools, this talks
to the Confluence REST API directly with an API token, so it can run unattended
(GitHub Actions, cron, etc.).

Required environment variables:
    CONFLUENCE_BASE_URL   e.g. https://your-site.atlassian.net/wiki
    CONFLUENCE_EMAIL      Atlassian account email that owns the API token
    CONFLUENCE_API_TOKEN  API token from https://id.atlassian.com/manage-profile/security/api-tokens
    CONFLUENCE_PAGE_ID    Numeric id of the tracker page to keep in sync
"""

import base64
import html
import os
import re

import httpx
from dotenv import load_dotenv

load_dotenv()


def _load_config() -> None:
    global CONFLUENCE_BASE_URL, CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN, CONFLUENCE_PAGE_ID
    CONFLUENCE_BASE_URL = os.getenv("CONFLUENCE_BASE_URL", "").rstrip("/")
    CONFLUENCE_EMAIL = os.getenv("CONFLUENCE_EMAIL")
    CONFLUENCE_API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN")
    CONFLUENCE_PAGE_ID = os.getenv("CONFLUENCE_PAGE_ID")


_load_config()


def refresh() -> None:
    """Re-read Confluence config from the environment (used by the Settings tab)."""
    _load_config()

# Status lozenge colours (Confluence storage uses capitalised colour names).
COLOUR_GREEN = "Green"
COLOUR_YELLOW = "Yellow"
COLOUR_RED = "Red"
COLOUR_GREY = "Grey"


def _require_config() -> None:
    missing = [
        name
        for name, value in (
            ("CONFLUENCE_BASE_URL", CONFLUENCE_BASE_URL),
            ("CONFLUENCE_EMAIL", CONFLUENCE_EMAIL),
            ("CONFLUENCE_API_TOKEN", CONFLUENCE_API_TOKEN),
            ("CONFLUENCE_PAGE_ID", CONFLUENCE_PAGE_ID),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing Confluence configuration: " + ", ".join(missing) + ". "
            "Set them in .env (local) or as GitHub Actions secrets."
        )


def _auth_header() -> str:
    raw = f"{CONFLUENCE_EMAIL}:{CONFLUENCE_API_TOKEN}".encode()
    return "Basic " + base64.b64encode(raw).decode()


def get_page(client: httpx.Client, page_id: str) -> dict:
    """Fetch a page's storage body and current version number."""
    _require_config()
    url = f"{CONFLUENCE_BASE_URL}/api/v2/pages/{page_id}"
    resp = client.get(
        url,
        params={"body-format": "storage"},
        headers={"Authorization": _auth_header(), "Accept": "application/json"},
    )
    resp.raise_for_status()
    data = resp.json()
    return {
        "title": data["title"],
        "version": data["version"]["number"],
        "storage": data["body"]["storage"]["value"],
        "webui": (data.get("_links", {}) or {}).get("webui", ""),
    }


def page_web_url(page_id: str, space_key: str | None = None) -> str:
    """Browser URL for a page. Uses the API's webui link (space-aware), which the
    bare /pages/{id} form is not, so the link actually resolves."""
    try:
        with httpx.Client(timeout=30) as client:
            webui = get_page(client, page_id).get("webui")
        if webui:
            return f"{CONFLUENCE_BASE_URL}{webui}"
    except Exception:  # noqa: BLE001 - fall back to a best-effort URL
        pass
    if space_key:
        return f"{CONFLUENCE_BASE_URL}/spaces/{space_key}/pages/{page_id}"
    return f"{CONFLUENCE_BASE_URL}/pages/{page_id}"


def update_page(
    client: httpx.Client,
    page_id: str,
    title: str,
    storage_body: str,
    current_version: int,
    message: str,
    parent_id: str | None = None,
) -> dict:
    """Replace a page's body, incrementing its version number.

    Pass parent_id to also re-parent the page (move it under a different page/folder).
    """
    _require_base_auth()
    url = f"{CONFLUENCE_BASE_URL}/api/v2/pages/{page_id}"
    payload = {
        "id": str(page_id),
        "status": "current",
        "title": title,
        "body": {"representation": "storage", "value": storage_body},
        "version": {"number": current_version + 1, "message": message},
    }
    if parent_id is not None:
        payload["parentId"] = str(parent_id)
    resp = client.put(
        url,
        json=payload,
        headers={
            "Authorization": _auth_header(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    resp.raise_for_status()
    return resp.json()


def _require_base_auth() -> None:
    """Lighter check for operations that don't need CONFLUENCE_PAGE_ID."""
    missing = [
        name
        for name, value in (
            ("CONFLUENCE_BASE_URL", CONFLUENCE_BASE_URL),
            ("CONFLUENCE_EMAIL", CONFLUENCE_EMAIL),
            ("CONFLUENCE_API_TOKEN", CONFLUENCE_API_TOKEN),
        )
        if not value
    ]
    if missing:
        raise RuntimeError(
            "Missing Confluence configuration: " + ", ".join(missing) + ". Set them in .env."
        )


def _json_headers() -> dict[str, str]:
    return {
        "Authorization": _auth_header(),
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def get_space_id(client: httpx.Client, space_key: str) -> str:
    """Resolve a space key (e.g. 'SIC') to its numeric space id."""
    _require_base_auth()
    resp = client.get(
        f"{CONFLUENCE_BASE_URL}/api/v2/spaces",
        params={"keys": space_key},
        headers={"Authorization": _auth_header(), "Accept": "application/json"},
    )
    resp.raise_for_status()
    results = resp.json().get("results", [])
    if not results:
        raise RuntimeError(f"No Confluence space found with key '{space_key}'.")
    return results[0]["id"]


def list_folder_children(client: httpx.Client, folder_id: str) -> list[dict]:
    """List direct children (pages) of a folder: dicts with id, title, type."""
    _require_base_auth()
    children: list[dict] = []
    cursor: str | None = None
    while True:
        params = {"limit": 250}
        if cursor:
            params["cursor"] = cursor
        resp = client.get(
            f"{CONFLUENCE_BASE_URL}/api/v2/folders/{folder_id}/direct-children",
            params=params,
            headers={"Authorization": _auth_header(), "Accept": "application/json"},
        )
        resp.raise_for_status()
        body = resp.json()
        children.extend(body.get("results", []))
        cursor = (body.get("_links", {}) or {}).get("next")
        if not cursor:
            break
        # `next` is a full path with a cursor query param; extract just the cursor.
        match = re.search(r"[?&]cursor=([^&]+)", cursor)
        cursor = match.group(1) if match else None
        if not cursor:
            break
    return children


def list_page_children(client: httpx.Client, page_id: str) -> list[dict]:
    """List direct child pages of a page: dicts with id, title, status."""
    _require_base_auth()
    children: list[dict] = []
    cursor: str | None = None
    while True:
        params = {"limit": 250}
        if cursor:
            params["cursor"] = cursor
        resp = client.get(
            f"{CONFLUENCE_BASE_URL}/api/v2/pages/{page_id}/children",
            params=params,
            headers={"Authorization": _auth_header(), "Accept": "application/json"},
        )
        resp.raise_for_status()
        body = resp.json()
        children.extend(body.get("results", []))
        nxt = (body.get("_links", {}) or {}).get("next")
        match = re.search(r"[?&]cursor=([^&]+)", nxt) if nxt else None
        cursor = match.group(1) if match else None
        if not cursor:
            break
    return children


# Labels used to tie a readable doc page to its Dify workflow, so the link
# survives workflow renames (the page title can change; the app id does not).
DOC_LABEL = "dify-doc"
APP_LABEL_PREFIX = "dify-app-"


def add_labels(client: httpx.Client, page_id: str, labels: list[str]) -> None:
    """Attach one or more global labels to a page (idempotent on Confluence's side)."""
    _require_base_auth()
    if not labels:
        return
    payload = [{"prefix": "global", "name": label} for label in labels]
    resp = client.post(
        f"{CONFLUENCE_BASE_URL}/rest/api/content/{page_id}/label",
        json=payload,
        headers=_json_headers(),
    )
    resp.raise_for_status()


def search_by_label(client: httpx.Client, label: str) -> list[dict]:
    """Return pages carrying a label: dicts with id, title, webui, labels (set)."""
    _require_base_auth()
    out: list[dict] = []
    start, limit = 0, 100
    while True:
        resp = client.get(
            f"{CONFLUENCE_BASE_URL}/rest/api/content/search",
            params={
                "cql": f'type=page and label="{label}"',
                "expand": "metadata.labels",
                "limit": limit,
                "start": start,
            },
            headers={"Authorization": _auth_header(), "Accept": "application/json"},
        )
        resp.raise_for_status()
        body = resp.json()
        results = body.get("results", [])
        for r in results:
            labels = {
                lab.get("name")
                for lab in (r.get("metadata", {}).get("labels", {}).get("results", []))
            }
            out.append(
                {
                    "id": r.get("id"),
                    "title": r.get("title"),
                    "webui": (r.get("_links", {}) or {}).get("webui", ""),
                    "labels": labels,
                }
            )
        if not results or start + len(results) >= body.get("totalSize", len(out)):
            break
        start += limit
    return out


def app_label(app_id: str) -> str:
    return f"{APP_LABEL_PREFIX}{app_id}"


def app_id_from_labels(labels: set[str]) -> str | None:
    for lab in labels:
        if lab and lab.startswith(APP_LABEL_PREFIX):
            return lab[len(APP_LABEL_PREFIX):]
    return None


def create_page(
    client: httpx.Client, space_id: str, parent_id: str, title: str, storage_body: str
) -> dict:
    """Create a new page under a parent (page or folder) and return the API response."""
    _require_base_auth()
    payload = {
        "spaceId": str(space_id),
        "status": "current",
        "title": title,
        "parentId": str(parent_id),
        "body": {"representation": "storage", "value": storage_body},
    }
    resp = client.post(
        f"{CONFLUENCE_BASE_URL}/api/v2/pages", json=payload, headers=_json_headers()
    )
    resp.raise_for_status()
    return resp.json()


def upload_attachment(
    client: httpx.Client,
    page_id: str,
    filename: str,
    content: bytes,
    content_type: str,
) -> dict:
    """Attach (or update) a file on a page. Idempotent: re-uploading the same
    filename creates a new version instead of failing."""
    _require_base_auth()
    base = f"{CONFLUENCE_BASE_URL}/rest/api/content/{page_id}/child/attachment"
    headers = {"Authorization": _auth_header(), "X-Atlassian-Token": "nocheck"}

    # Does an attachment with this name already exist?
    existing = client.get(
        base,
        params={"filename": filename},
        headers={"Authorization": _auth_header(), "Accept": "application/json"},
    )
    existing.raise_for_status()
    results = existing.json().get("results", [])

    files = {"file": (filename, content, content_type)}
    data = {"minorEdit": "true", "comment": "Generated by DSL readable converter"}
    if results:
        att_id = results[0]["id"]
        url = f"{base}/{att_id}/data"
    else:
        url = base
    resp = client.post(url, files=files, data=data, headers=headers)
    resp.raise_for_status()
    return resp.json()


def image_macro(filename: str, width: int | None = 760) -> str:
    """Render an attached image (by filename) in storage format."""
    width_attr = f' ac:width="{width}"' if width else ""
    return (
        f'<ac:image ac:align="center"{width_attr}>'
        f'<ri:attachment ri:filename="{html.escape(filename)}" />'
        "</ac:image>"
    )


def status_macro(title: str, colour: str) -> str:
    """Render a Confluence status lozenge in storage format."""
    return (
        '<ac:structured-macro ac:name="status">'
        f'<ac:parameter ac:name="colour">{colour}</ac:parameter>'
        f'<ac:parameter ac:name="title">{html.escape(title)}</ac:parameter>'
        "</ac:structured-macro>"
    )


def info_panel(text_html: str) -> str:
    """Render an info panel in storage format."""
    return (
        '<ac:structured-macro ac:name="info"><ac:rich-text-body>'
        f"<p>{text_html}</p>"
        "</ac:rich-text-body></ac:structured-macro>"
    )


def flag_row_removed(row_html: str) -> str:
    """Replace the first cell of a row with a red 'Removed from Dify' lozenge."""
    replacement = f"<td><p>{status_macro('Removed from Dify', COLOUR_RED)}</p></td>"
    return re.sub(r"<td>.*?</td>", replacement, row_html, count=1, flags=re.DOTALL)
