"""Read-only governance dashboard data.

Combines the live Dify app list with the Confluence tracker rows the same way
sync_tracker does, but never writes Confluence. Returns one record per workflow
plus summary counts.
"""

import asyncio
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends

import confluence
import dify_api
import sync_tracker
from api.auth import require_auth

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


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
