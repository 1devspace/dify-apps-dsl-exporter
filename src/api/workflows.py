"""Read-only governance dashboard data.

Combines the live Dify app list with the Confluence tracker rows the same way
sync_tracker does, but never writes Confluence. Returns one record per workflow
plus summary counts.
"""

import asyncio
import os
import re
from datetime import datetime, timezone

import httpx
import yaml
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

import confluence
import dify_api
import sync_tracker
from api.auth import require_admin, require_auth

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

ENV_TAGS = {"prod", "dev", "test"}


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", (name or "workflow").strip())
    return cleaned or "workflow"


def _build_dashboard() -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    dify_apps = asyncio.run(sync_tracker.fetch_dify_apps())
    dify_by_id = {a["id"]: a for a in dify_apps if a.get("id")}

    with httpx.Client(timeout=60) as client:
        page = confluence.get_page(client, confluence.CONFLUENCE_PAGE_ID)
    _, existing_rows = sync_tracker.parse_existing_rows(page["storage"])
    tracked_ids = {r["app_id"] for r in existing_rows}

    records: list[dict] = []
    for row in existing_rows:
        app = dify_by_id.get(row["app_id"])
        live = app is not None
        tags = row.get("tags", "")
        records.append(
            {
                "app_id": row["app_id"],
                # Dify owns the workflow name: prefer the live name so renames in
                # Dify show up immediately (tracker name is only a fallback, e.g.
                # for workflows removed from Dify).
                "name": (app.get("name") if app else "") or row["name"],
                # Tracker's assigned owner only. We intentionally do NOT fall back
                # to the Dify creator, otherwise unassigning yourself as the sole
                # author would "reappear" from the Dify author_name.
                "author": row["author"],
                "tags": tags,
                "decision": row.get("decision", ""),
                "url": row.get("url", ""),
                "informations_added": row.get("is_done", False),
                "missing_env_tag": not sync_tracker.has_env_tag(tags),
                "live_in_dify": live,
                "removed_from_dify": not live,
                "source": "tracker",
            }
        )

    # Dify apps not yet on the tracker page.
    for app in dify_apps:
        if not app.get("id") or app["id"] in tracked_ids:
            continue
        tags = app.get("tags", "")
        records.append(
            {
                "app_id": app["id"],
                "name": app.get("name") or app["id"],
                "author": app.get("author", ""),
                "tags": tags,
                "decision": "",
                "url": sync_tracker.workflow_url(app["id"]),
                "informations_added": False,
                "missing_env_tag": not sync_tracker.has_env_tag(tags),
                "live_in_dify": True,
                "removed_from_dify": False,
                "source": "new",
            }
        )

    live = [r for r in records if r["live_in_dify"]]
    summary = {
        "total_records": len(records),
        "live": len(live),
        "new": len([r for r in records if r["source"] == "new"]),
        "removed_from_dify": len([r for r in records if r["removed_from_dify"]]),
        "pending": len([r for r in live if not r["informations_added"]]),
        "missing_env_tag": len([r for r in live if r["missing_env_tag"]]),
        "marked_delete": len([r for r in live if r["decision"].strip().lower() == "delete"]),
    }
    page_url = (
        f"{confluence.CONFLUENCE_BASE_URL}{page['webui']}"
        if page.get("webui")
        else f"{confluence.CONFLUENCE_BASE_URL}/pages/{confluence.CONFLUENCE_PAGE_ID}"
    )
    return {
        "summary": summary,
        "records": records,
        "synced_at": today,
        "tracker_url": page_url,
        "dify_host": dify_api.DIFY_ORIGIN,
    }


@router.get("")
async def list_workflows(user: dict = Depends(require_auth)) -> dict:
    # Run the blocking client work off the event loop.
    return await asyncio.to_thread(_build_dashboard)


# Where `./run.sh readable --output confluence` publishes the per-workflow docs.
DOCS_INDEX_TITLE = "Dify Workflows — Index"


def _doc_links() -> dict:
    """Map each published readable doc page title -> its Confluence URL.

    Reads the existing pages under the docs folder/index; never creates anything.
    """
    # Read dynamically so the Settings tab can change them without a restart.
    DOCS_PARENT_ID = os.getenv("CONFLUENCE_DOCS_PARENT_ID", "423952430")
    DOCS_SPACE = os.getenv("CONFLUENCE_DOCS_SPACE", "SIC")
    links: dict[str, str] = {}
    links_by_id: dict[str, str] = {}
    index_url: str | None = None
    with httpx.Client(timeout=60) as client:
        children = confluence.list_folder_children(client, DOCS_PARENT_ID)
        index_pid: str | None = None
        for c in children:
            if c.get("type") != "page":
                continue
            if c["title"] == DOCS_INDEX_TITLE:
                index_pid = c["id"]
                continue
            links[c["title"]] = c["id"]
        if index_pid:
            index_url = f"{confluence.CONFLUENCE_BASE_URL}/spaces/{DOCS_SPACE}/pages/{index_pid}"
            for c in confluence.list_page_children(client, index_pid):
                if c["title"] != DOCS_INDEX_TITLE:
                    links[c["title"]] = c["id"]
        # Rename-safe map: Dify app id -> doc URL, via the page's dify-app-<id> label.
        try:
            for p in confluence.search_by_label(client, confluence.DOC_LABEL):
                appid = confluence.app_id_from_labels(p.get("labels", set()))
                if appid and p.get("webui"):
                    links_by_id[appid] = f"{confluence.CONFLUENCE_BASE_URL}{p['webui']}"
        except httpx.HTTPError:
            pass
    return {
        "links": {
            title: f"{confluence.CONFLUENCE_BASE_URL}/spaces/{DOCS_SPACE}/pages/{pid}"
            for title, pid in links.items()
        },
        "links_by_id": links_by_id,
        "index_url": index_url,
    }


@router.get("/doc-links")
async def doc_links(user: dict = Depends(require_auth)) -> dict:
    return await asyncio.to_thread(_doc_links)


class EnvTagsBody(BaseModel):
    tags: list[str]


@router.post("/{app_id}/env-tags")
async def add_env_tags(app_id: str, body: EnvTagsBody, user: dict = Depends(require_auth)) -> dict:
    """Bind one or more environment tags (prod/dev/test) to a Dify app.

    Additive only (matches sync_env_tags): never unbinds existing tags. Missing
    global tags are created automatically.
    """
    wanted = {t.strip().lower() for t in body.tags if t.strip()} & ENV_TAGS
    if not wanted:
        raise HTTPException(status_code=400, detail="Provide at least one of: prod, dev, test")

    async with httpx.AsyncClient(timeout=60) as client:
        token = await dify_api.login_and_get_token(client)
        name_to_id = {t["name"].lower(): t["id"] for t in await dify_api.list_tags(token, client)}
        ids: list[str] = []
        for name in sorted(wanted):
            if name not in name_to_id:
                created = await dify_api.create_tag(token, client, name)
                name_to_id[name] = created["id"]
            ids.append(name_to_id[name])
        await dify_api.bind_tags(token, client, ids, app_id)
    return {"ok": True, "added": sorted(wanted)}


class AuthorBody(BaseModel):
    author: str = ""


@router.post("/{app_id}/author")
async def assign_author(
    app_id: str, body: AuthorBody, user: dict = Depends(require_auth)
) -> dict:
    """Set the tracker Author cell for a workflow. Defaults to the current user."""
    name = body.author.strip() or user.get("name") or user.get("email") or ""
    if not name:
        raise HTTPException(status_code=400, detail="No author name available")

    def _do() -> bool:
        with httpx.Client(timeout=60) as client:
            return sync_tracker.assign_author(client, app_id, name)

    ok = await asyncio.to_thread(_do)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Workflow is not on the tracker yet. Run Sync first, then assign.",
        )
    return {"ok": True, "author": name}


@router.post("/{app_id}/author/unassign")
async def unassign_author(
    app_id: str, body: AuthorBody, user: dict = Depends(require_auth)
) -> dict:
    """Remove a name from the tracker Author cell. Defaults to the current user."""
    name = body.author.strip() or user.get("name") or user.get("email") or ""
    if not name:
        raise HTTPException(status_code=400, detail="No author name available")

    def _do() -> bool:
        with httpx.Client(timeout=60) as client:
            return sync_tracker.remove_author(client, app_id, name)

    ok = await asyncio.to_thread(_do)
    if not ok:
        raise HTTPException(status_code=409, detail="Workflow is not on the tracker.")
    return {"ok": True, "removed": name}


@router.delete("/{app_id}/env-tags/{env}")
async def remove_env_tag(app_id: str, env: str, user: dict = Depends(require_auth)) -> dict:
    """Unbind a single environment tag (prod/dev/test) from a Dify app."""
    name = env.strip().lower()
    if name not in ENV_TAGS:
        raise HTTPException(status_code=400, detail="env must be one of: prod, dev, test")

    async with httpx.AsyncClient(timeout=60) as client:
        token = await dify_api.login_and_get_token(client)
        name_to_id = {t["name"].lower(): t["id"] for t in await dify_api.list_tags(token, client)}
        tag_id = name_to_id.get(name)
        if tag_id:
            await dify_api.unbind_tag(token, client, tag_id, app_id)
    return {"ok": True, "removed": name}


@router.delete("/{app_id}")
async def delete_workflow(app_id: str, user: dict = Depends(require_admin)) -> dict:
    """Delete a single workflow from Dify (admin only).

    Unlike prune, this does not archive a YAML backup or flag the tracker; the
    next sync will mark the row "Removed from Dify".
    """
    async with httpx.AsyncClient(timeout=60) as client:
        token = await dify_api.login_and_get_token(client)
        await dify_api.execute_api(
            client, f"{dify_api.BASE_URL}/apps/{app_id}", access_token=token, method_type="DELETE"
        )
    return {"ok": True}


@router.get("/{app_id}/export")
async def export_workflow(
    app_id: str, name: str | None = None, user: dict = Depends(require_admin)
) -> Response:
    """Download a single workflow's DSL as a YAML file."""
    async with httpx.AsyncClient(timeout=120) as client:
        token = await dify_api.login_and_get_token(client)
        data = await dify_api.export_app(token, app_id, client)
    filename = f"{_safe_filename(name or app_id)}.yml"
    return Response(
        content=data,
        media_type="application/x-yaml",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{app_id}/readable")
async def readable_workflow(
    app_id: str, name: str | None = None, user: dict = Depends(require_auth)
) -> dict:
    """Return a human-readable Markdown (with a Mermaid graph) for a workflow."""
    async with httpx.AsyncClient(timeout=120) as client:
        token = await dify_api.login_and_get_token(client)
        data = await dify_api.export_app(token, app_id, client)
    try:
        dsl = yaml.safe_load(data)
    except yaml.YAMLError as exc:
        raise HTTPException(status_code=502, detail=f"Could not parse DSL: {exc}")
    import dsl_readable  # lazy: heavy module, only needed for this endpoint

    blocks = dsl_readable.build_blocks(dsl, source_name=name or app_id)
    markdown = dsl_readable.blocks_to_markdown(blocks)
    return {"markdown": markdown}
