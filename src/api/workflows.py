"""Read-only governance dashboard data.

Combines the live Dify app list with the Confluence tracker rows the same way
sync_tracker does, but never writes Confluence. Returns one record per workflow
plus summary counts.
"""

import asyncio
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
                "name": row["name"] or (app or {}).get("name", ""),
                "author": row["author"] or (app or {}).get("author", ""),
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
    page_url = f"{confluence.CONFLUENCE_BASE_URL}/pages/{confluence.CONFLUENCE_PAGE_ID}"
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
    app_id: str, name: str | None = None, user: dict = Depends(require_auth)
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
