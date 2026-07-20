"""Copy environment tags (prod/dev/test) from the Confluence tracker into Dify.

People sometimes record a workflow's environment in the tracker's "Tags" column
but forget to tag the app in Dify itself. Since the tracker is a mirror of Dify,
those Confluence-only tags get lost on the next sync. This command reads the env
values from the tracker and binds the missing ones onto the matching Dify apps.

It is additive only: it never removes tags, and it only touches the environment
tags (prod/dev/test) - other tags are left untouched. Missing global tags are
created automatically.

Usage:
    python src/sync_env_tags.py            # apply the missing env tags in Dify
    python src/sync_env_tags.py --dry-run  # show what would change, change nothing
"""

import argparse
import asyncio

import httpx

import confluence
import dify_api
import sync_tracker

ENV_TAGS = {"prod", "dev", "test"}


def _env_tokens(tags: str) -> set[str]:
    return {t.strip().lower() for t in (tags or "").split(",") if t.strip()} & ENV_TAGS


def _read_tracker_env() -> dict[str, set[str]]:
    """Return {app_id: {env tags recorded in the tracker}} for rows that have any."""
    with httpx.Client(timeout=60) as client:
        page = confluence.get_page(client, confluence.CONFLUENCE_PAGE_ID)
    _, rows = sync_tracker.parse_existing_rows(page["storage"])
    result: dict[str, set[str]] = {}
    for row in rows:
        env = _env_tokens(row.get("tags", ""))
        if env:
            result[row["app_id"]] = env
    return result


async def _run(dry_run: bool) -> dict:
    tracker_env = _read_tracker_env()

    async with httpx.AsyncClient(timeout=60) as client:
        access_token = await dify_api.login_and_get_token(client)
        apps = await dify_api.get_app_details(access_token, client)
        by_id = {a["id"]: a for a in apps if a.get("id")}

        # Compute the missing env tags per app (recorded in tracker, absent in Dify).
        plan: list[tuple[str, str, list[str]]] = []  # (app_id, name, tags_to_add)
        for app_id, env in tracker_env.items():
            app = by_id.get(app_id)
            if not app:
                continue  # row no longer maps to a live Dify app
            existing = _env_tokens(app.get("tags", ""))
            missing = sorted(env - existing)
            if missing:
                plan.append((app_id, app.get("name") or app_id, missing))

        print(f"Workflows needing env tags added in Dify: {len(plan)}")
        for _, name, missing in plan:
            print(f"  + {name}: {missing}")

        if not plan:
            print("Nothing to do; Dify already matches the tracker.")
            return {"updated": 0, "plan": []}

        if dry_run:
            print("\nDry run: no changes made.")
            return {"updated": 0, "plan": plan}

        # Resolve (and create as needed) the global tag ids.
        name_to_id = {t["name"].lower(): t["id"] for t in await dify_api.list_tags(access_token, client)}

        async def tag_id(name: str) -> str:
            if name not in name_to_id:
                created = await dify_api.create_tag(access_token, client, name)
                name_to_id[name] = created["id"]
                print(f"  created global tag '{name}'")
            return name_to_id[name]

        updated = 0
        for app_id, name, missing in plan:
            ids = [await tag_id(t) for t in missing]
            await dify_api.bind_tags(access_token, client, ids, app_id)
            print(f"  tagged {name} with {missing}")
            updated += 1

    print(f"\nDone: env tags synced onto {updated} workflow(s).")
    return {"updated": updated, "plan": plan}


def run(dry_run: bool = False) -> dict:
    return asyncio.run(_run(dry_run))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Copy env tags (prod/dev/test) from the Confluence tracker into Dify."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would change without modifying Dify."
    )
    args = parser.parse_args()
    run(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
