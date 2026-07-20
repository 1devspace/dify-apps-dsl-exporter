"""Weekly tracker sync: refresh the Confluence page from Dify, then notify Slack.

Flow:
  1. Log in to Dify and fetch every app with its metadata.
  2. Read the current Confluence tracker page (storage format).
  3. Merge by App ID:
       - existing rows are preserved verbatim (keeps all human-curated columns
         such as Working?, Decision, Notes, Author & contributor(s), Tags);
       - apps not yet on the page are appended as new rows (Informations added?
         = FALSE) with metadata pulled from Dify;
       - rows whose App ID no longer exists in Dify are flagged with a red
         "Removed from Dify" lozenge (the row is kept for history).
  4. Write the rebuilt page back (version + 1).
  5. Post a status summary + the list of workflows pending info input to Slack.

Usage:
    python src/sync_tracker.py            # full sync + Slack notification
    python src/sync_tracker.py --no-slack # update Confluence only
    python src/sync_tracker.py --dry-run  # compute + print, change nothing
"""

import argparse
import asyncio
import html
import os
import threading
from datetime import datetime, timezone

import httpx
from bs4 import BeautifulSoup

# Serialise all single-cell writes to the tracker page. Each writer does a
# read-modify-write on the same Confluence page; without this, two near-
# simultaneous edits (e.g. optimistic UI saves) would read the same version and
# the second write would 409. The lock keeps each edit reading a fresh version.
_write_lock = threading.Lock()

import confluence
import dify_api
import slack_notify

# Human label for this deployment, used in the Confluence page heading and Slack
# messages. Override with PROJECT_LABEL (e.g. "Acme Dify Workflows").
PROJECT_LABEL = (os.getenv("PROJECT_LABEL") or "Dify Workflows").strip()
PAGE_TITLE = f"{PROJECT_LABEL} Tracker"
WORKFLOW_LINK_TEXT = "Open workflow"
# A workflow should carry at least one of these environment tags.
ENV_TAGS = {"prod", "dev", "test"}


def has_env_tag(tags: str) -> bool:
    tokens = {t.strip().lower() for t in (tags or "").split(",") if t.strip()}
    return bool(tokens & ENV_TAGS)


def ts_to_date(ts) -> str:
    """Convert a Dify unix timestamp (seconds) to YYYY-MM-DD."""
    if not ts:
        return ""
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d")
    except (ValueError, OSError, TypeError):
        return ""


def workflow_url(app_id: str) -> str:
    return f"{dify_api.DIFY_ORIGIN}/app/{app_id}/workflow"


async def fetch_dify_apps() -> list[dict]:
    async with httpx.AsyncClient(timeout=60) as client:
        access_token = await dify_api.login_and_get_token(client)
        return await dify_api.get_app_details(access_token, client)


def _status_title(cell) -> str:
    """Read the title of a status lozenge inside a cell, if present."""
    macro = cell.find("ac:structured-macro")
    if macro:
        for param in macro.find_all("ac:parameter"):
            if param.get("ac:name") == "title":
                return param.get_text(strip=True)
    return cell.get_text(strip=True)


def parse_existing_rows(storage: str) -> tuple[str, list[dict]]:
    """Parse the tracker table.

    :return: (header row HTML, list of row dicts keyed by App ID)
    """
    soup = BeautifulSoup(storage, "html.parser")
    table = soup.find("table")
    if table is None:
        raise RuntimeError("Tracker page has no table; cannot sync safely.")

    header_html = ""
    rows: list[dict] = []
    for tr in table.find_all("tr"):
        if tr.find("th") is not None:
            header_html = str(tr)
            continue
        cells = tr.find_all("td")
        if not cells:
            continue
        app_id = cells[-1].get_text(strip=True)
        if not app_id:
            continue
        name = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        tags = cells[3].get_text(strip=True) if len(cells) > 3 else ""
        working = _status_title(cells[4]).strip() if len(cells) > 4 else ""
        decision = _status_title(cells[5]).strip() if len(cells) > 5 else ""
        author = cells[6].get_text(strip=True) if len(cells) > 6 else ""
        created = cells[7].get_text(strip=True) if len(cells) > 7 else ""
        updated = cells[8].get_text(strip=True) if len(cells) > 8 else ""
        notes = cells[9].get_text(" ", strip=True) if len(cells) > 9 else ""
        link_tag = tr.find("a")
        url = link_tag.get("href") if link_tag else workflow_url(app_id)
        is_done = _status_title(cells[0]).strip().upper() == "TRUE"
        rows.append(
            {
                "app_id": app_id,
                "name": name,
                "tags": tags,
                "working": working,
                "decision": decision,
                "author": author,
                "created": created,
                "updated": updated,
                "notes": notes,
                "url": url,
                "is_done": is_done,
                "html": str(tr),
            }
        )
    return header_html, rows


def assign_author(client: httpx.Client, app_id: str, author: str) -> bool:
    """Set the Author cell for a single tracked row, preserving everything else.

    Returns False if the app has no row on the tracker yet (e.g. still "New").
    """
    page_id = confluence.CONFLUENCE_PAGE_ID
    with _write_lock:
        page = confluence.get_page(client, page_id)
        soup = BeautifulSoup(page["storage"], "html.parser")
        table = soup.find("table")
        if table is None:
            raise RuntimeError("Tracker page has no table; cannot assign author.")

        target = None
        for tr in table.find_all("tr"):
            if tr.find("th") is not None:
                continue
            cells = tr.find_all("td")
            if not cells:
                continue
            if cells[-1].get_text(strip=True) == app_id:
                target = cells
                break

        if target is None or len(target) <= 6:
            return False

        author_cell = target[6]
        author_cell.clear()
        p = soup.new_tag("p")
        p.string = author
        author_cell.append(p)

        confluence.update_page(
            client,
            page_id,
            page["title"],
            str(soup),
            page["version"],
            f"Assign author '{author}' to {app_id}",
        )
    return True


def _find_row_cells(table, app_id: str):
    """Return the <td> list for the row whose last cell holds app_id, else None."""
    for tr in table.find_all("tr"):
        if tr.find("th") is not None:
            continue
        cells = tr.find_all("td")
        if cells and cells[-1].get_text(strip=True) == app_id:
            return cells
    return None


def remove_author(client: httpx.Client, app_id: str, author: str) -> bool:
    """Remove a single name from a tracked row's Author cell, keeping co-authors.

    Returns False if the app has no row on the tracker yet.
    """
    page_id = confluence.CONFLUENCE_PAGE_ID
    with _write_lock:
        page = confluence.get_page(client, page_id)
        soup = BeautifulSoup(page["storage"], "html.parser")
        table = soup.find("table")
        if table is None:
            raise RuntimeError("Tracker page has no table; cannot edit author.")

        cells = _find_row_cells(table, app_id)
        if cells is None or len(cells) <= 6:
            return False

        author_cell = cells[6]
        current = [p.strip() for p in author_cell.get_text().split(",") if p.strip()]
        remaining = [p for p in current if p.lower() != author.strip().lower()]

        author_cell.clear()
        p = soup.new_tag("p")
        p.string = ", ".join(remaining)
        author_cell.append(p)

        confluence.update_page(
            client,
            page_id,
            page["title"],
            str(soup),
            page["version"],
            f"Remove author '{author}' from {app_id}",
        )
    return True


# Canonical governance vocabularies + lozenge colours, matching the tracker.
DECISION_COLOURS = {
    "keep": confluence.COLOUR_GREEN,
    "delete": confluence.COLOUR_RED,
    "pending": confluence.COLOUR_GREY,
    "review": confluence.COLOUR_YELLOW,
}
WORKING_COLOURS = {
    "working": confluence.COLOUR_GREEN,
    "has some bugs": confluence.COLOUR_YELLOW,
    "not working": confluence.COLOUR_RED,
}


def _set_row_cell(
    client: httpx.Client, app_id: str, index: int, inner_html: str, message: str
) -> bool:
    """Replace one cell (by column index) of a tracked row, preserving the rest.

    ``inner_html`` is storage-format markup placed inside a fresh ``<p>`` (a
    status macro, escaped text, or empty to clear). Returns False if the app has
    no row on the tracker yet.
    """
    page_id = confluence.CONFLUENCE_PAGE_ID
    with _write_lock:
        page = confluence.get_page(client, page_id)
        soup = BeautifulSoup(page["storage"], "html.parser")
        table = soup.find("table")
        if table is None:
            raise RuntimeError("Tracker page has no table; cannot edit row.")

        cells = _find_row_cells(table, app_id)
        if cells is None or len(cells) <= index:
            return False

        cell = cells[index]
        cell.clear()
        fragment = BeautifulSoup(f"<p>{inner_html}</p>", "html.parser")
        cell.append(fragment)

        confluence.update_page(
            client, page_id, page["title"], str(soup), page["version"], message
        )
    return True


def set_decision(client: httpx.Client, app_id: str, value: str) -> bool:
    """Set the Decision cell (col 5) to a coloured status lozenge (empty clears it)."""
    value = (value or "").strip()
    inner = ""
    if value:
        colour = DECISION_COLOURS.get(value.lower(), confluence.COLOUR_GREY)
        inner = confluence.status_macro(value, colour)
    return _set_row_cell(client, app_id, 5, inner, f"Set decision '{value}' for {app_id}")


def set_working(client: httpx.Client, app_id: str, value: str) -> bool:
    """Set the Working? cell (col 4) to a coloured status lozenge (empty clears it)."""
    value = (value or "").strip()
    inner = ""
    if value:
        colour = WORKING_COLOURS.get(value.lower(), confluence.COLOUR_GREY)
        inner = confluence.status_macro(value, colour)
    return _set_row_cell(client, app_id, 4, inner, f"Set working '{value}' for {app_id}")


def set_notes(client: httpx.Client, app_id: str, notes: str) -> bool:
    """Set the Notes cell (col 9) to plain text (empty clears it)."""
    notes = notes or ""
    return _set_row_cell(client, app_id, 9, html.escape(notes), f"Update notes for {app_id}")


def update_row_name(row_html: str, new_name: str) -> str:
    """Return the row HTML with its Name cell (column 1) replaced by new_name."""
    soup = BeautifulSoup(row_html, "html.parser")
    tr = soup.find("tr")
    if tr is None:
        return row_html
    cells = tr.find_all("td")
    if len(cells) > 1:
        cell = cells[1]
        cell.clear()
        p = soup.new_tag("p")
        p.string = new_name
        cell.append(p)
    return str(tr)


def build_new_row(app: dict, today: str) -> str:
    name = html.escape(app.get("name") or "")
    tags = html.escape(app.get("tags") or "")
    author = html.escape(app.get("author") or "")
    created = ts_to_date(app.get("created_at"))
    updated = ts_to_date(app.get("updated_at"))
    url = workflow_url(app["id"])
    cells = [
        f"<td><p>{confluence.status_macro('FALSE', confluence.COLOUR_GREY)}</p></td>",
        f"<td><p>{name}</p></td>",
        f'<td><p><a href="{url}">{WORKFLOW_LINK_TEXT}</a></p></td>',
        f"<td><p>{tags}</p></td>",
        "<td><p></p></td>",
        "<td><p></p></td>",
        f"<td><p>{author}</p></td>",
        f"<td><p>{created}</p></td>",
        f"<td><p>{updated}</p></td>",
        f"<td><p>Auto-added from Dify export {today}</p></td>",
        f"<td><p>{html.escape(app['id'])}</p></td>",
    ]
    return "<tr>" + "".join(cells) + "</tr>"


def build_body(header_html: str, rows_html: list[str], stats: dict, today: str) -> str:
    origin = dify_api.DIFY_ORIGIN
    panel_text = (
        f'Auto-synced from Dify. Host: <a href="{origin}">{html.escape(origin)}</a>. '
        f"Total live workflows: {stats['total']} &middot; "
        f"Pending info input: {stats['pending']} &middot; "
        f"Missing env tag: {stats.get('missing_tags', 0)} &middot; "
        f"New this run: {stats['new']} &middot; "
        f"Removed from Dify: {stats['removed']}. "
        f"Last synced: {today}."
    )
    table = "<table><tbody>" + header_html + "".join(rows_html) + "</tbody></table>"
    return f"<h1>{PAGE_TITLE}</h1>" + confluence.info_panel(panel_text) + table


def merge(existing_rows: list[dict], dify_apps: list[dict], today: str):
    """Compute the rebuilt rows, stats, and pending list."""
    dify_by_id = {a["id"]: a for a in dify_apps if a.get("id")}
    existing_ids = {r["app_id"] for r in existing_rows}

    rows_html: list[str] = []
    pending: list[dict] = []
    missing_tags: list[dict] = []
    removed = 0

    # Preserve existing rows in order; flag any that vanished from Dify.
    for row in existing_rows:
        app = dify_by_id.get(row["app_id"])
        if app is not None:
            row_html = row["html"]
            name = row["name"]
            # Dify owns the name: propagate renames into the tracker cell.
            dify_name = (app.get("name") or "").strip()
            if dify_name and dify_name != row["name"]:
                row_html = update_row_name(row_html, dify_name)
                name = dify_name
            rows_html.append(row_html)
            entry = {"name": name, "url": row["url"], "author": row["author"]}
            if not row["is_done"]:
                pending.append(entry)
            if not has_env_tag(row.get("tags", "")):
                missing_tags.append(entry)
        else:
            rows_html.append(confluence.flag_row_removed(row["html"]))
            removed += 1

    # Append apps that are not yet tracked.
    new_apps = [a for a in dify_apps if a.get("id") and a["id"] not in existing_ids]
    for app in new_apps:
        rows_html.append(build_new_row(app, today))
        entry = {
            "name": app.get("name") or app["id"],
            "url": workflow_url(app["id"]),
            "author": app.get("author") or "",
        }
        pending.append(entry)
        if not has_env_tag(app.get("tags", "")):
            missing_tags.append(entry)

    stats = {
        "total": len(dify_by_id),
        "new": len(new_apps),
        "removed": removed,
        "pending": len(pending),
        "missing_tags": len(missing_tags),
    }
    return rows_html, stats, pending, missing_tags


def update_confluence(
    client: httpx.Client, dify_apps: list[dict], today: str, version_message: str | None = None
) -> tuple[dict, list[dict], list[dict]]:
    """Read the tracker, merge with live Dify apps, and write it back.

    Shared by the routine sync and the prune command so deletions are flagged
    ("Removed from Dify") the same way. Returns (stats, pending, missing_tags).
    """
    page_id = confluence.CONFLUENCE_PAGE_ID
    page = confluence.get_page(client, page_id)
    header_html, existing_rows = parse_existing_rows(page["storage"])
    print(f"  {len(existing_rows)} rows on the page (version {page['version']}).")

    rows_html, stats, pending, missing_tags = merge(existing_rows, dify_apps, today)
    print(
        f"  Merge result -> total: {stats['total']}, new: {stats['new']}, "
        f"removed: {stats['removed']}, pending: {stats['pending']}, "
        f"missing env tag: {stats['missing_tags']}"
    )

    body = build_body(header_html, rows_html, stats, today)
    message = version_message or (
        f"Auto-sync: {stats['new']} new, {stats['removed']} removed ({today})"
    )
    confluence.update_page(client, page_id, page["title"], body, page["version"], message)
    print(f"  Confluence page updated to version {page['version'] + 1}.")
    return stats, pending, missing_tags


def run(dry_run: bool = False, notify: bool = True) -> dict:
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print("Fetching apps from Dify...")
    dify_apps = asyncio.run(fetch_dify_apps())
    print(f"  {len(dify_apps)} apps found.")

    page_id = confluence.CONFLUENCE_PAGE_ID
    page_url = confluence.page_web_url(page_id)

    if dry_run:
        with httpx.Client(timeout=60) as client:
            print("Reading Confluence page...")
            page = confluence.get_page(client, page_id)
            _, existing_rows = parse_existing_rows(page["storage"])
            _, stats, pending, missing_tags = merge(existing_rows, dify_apps, today)
            print(
                f"  Merge result -> total: {stats['total']}, new: {stats['new']}, "
                f"removed: {stats['removed']}, pending: {stats['pending']}, "
                f"missing env tag: {stats['missing_tags']}"
            )
        print("Dry run: not updating Confluence or posting to Slack.")
        return {"stats": stats, "pending": pending, "missing_tags": missing_tags}

    with httpx.Client(timeout=60) as client:
        print("Reading Confluence page...")
        stats, pending, missing_tags = update_confluence(client, dify_apps, today)

    if notify:
        print("Posting status to Slack...")
        messages = slack_notify.build_messages(stats, pending, missing_tags, page_url)
        slack_notify.post_all(messages)
        print(f"  Slack: {len(messages)} message(s) sent.")

    return {"stats": stats, "pending": pending, "missing_tags": missing_tags}


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync the Dify workflow tracker to Confluence and notify Slack.")
    parser.add_argument("--dry-run", action="store_true", help="Compute and print without changing anything.")
    parser.add_argument("--no-slack", action="store_true", help="Update Confluence but skip the Slack notification.")
    args = parser.parse_args()
    run(dry_run=args.dry_run, notify=not args.no_slack)


if __name__ == "__main__":
    main()
