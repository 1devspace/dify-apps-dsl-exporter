"""Post the workflow-tracker status to Slack via an incoming webhook.

Required environment variable:
    SLACK_WEBHOOK_URL   Incoming webhook URL for the target channel.

The status is split into one or more messages so it never exceeds Slack limits:
  1. Weekly status + workflows pending information input (grouped by contributor).
  2. Workflows missing an environment tag (prod/dev/test), grouped by contributor.
Large author groups are capped, and if a single message would exceed Slack's
50-block limit the author sections are chunked across several messages.
"""

import json
import os

import httpx
from dotenv import load_dotenv

load_dotenv()

SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

# Human label for this deployment, shown in message titles. Override with
# PROJECT_LABEL (e.g. "Acme Dify Workflows").
PROJECT_LABEL = (os.getenv("PROJECT_LABEL") or "Dify Workflows").strip()


def refresh() -> None:
    """Re-read the Slack webhook from the environment (used by the Settings tab)."""
    global SLACK_WEBHOOK_URL
    SLACK_WEBHOOK_URL = os.getenv("SLACK_WEBHOOK_URL")

# Map tracker contributor names (lowercased) to Slack member IDs so the message
# can @-mention people. Configure via the SLACK_USER_MAP env var (JSON like
# {"name": "U012ABC"}). Names not found are shown as plain bold text.
NAME_TO_SLACK_ID: dict[str, str] = {}
try:
    NAME_TO_SLACK_ID.update(
        {k.lower(): v for k, v in json.loads(os.getenv("SLACK_USER_MAP", "{}")).items()}
    )
except (ValueError, AttributeError):
    pass

# Normalise alternate contributor names to a canonical one before grouping, so
# they merge into a single mention (e.g. an alias is the same person as "mo").
# Configure via SLACK_NAME_ALIASES (JSON like {"alias": "canonical"}).
NAME_ALIASES: dict[str, str] = {}
try:
    NAME_ALIASES.update(
        {k.lower(): str(v).lower() for k, v in json.loads(os.getenv("SLACK_NAME_ALIASES", "{}")).items()}
    )
except (ValueError, AttributeError):
    pass


def mention(author: str) -> str:
    """Render a contributor as a Slack @-mention if known, else bold plain text."""
    slack_id = NAME_TO_SLACK_ID.get(author.strip().lower())
    return f"<@{slack_id}>" if slack_id else f"*{author}*"

# Label used when a workflow has no recorded author/contributor.
UNASSIGNED_LABEL = "Unassigned"
# Placeholder author values that mean "no real owner". Kept in sync with the web
# app (frontend UNKNOWN_AUTHORS) so both treat these as Unassigned.
PLACEHOLDER_AUTHORS = {"unassigned", "unknown", "n/a", "na", "tbd", "-", "—"}
# Cap workflows listed per author group to keep each Slack block readable.
MAX_PER_AUTHOR = 15
# Slack allows at most 50 blocks per message; stay safely under it.
MAX_BLOCKS = 46


def group_by_author(items: list[dict]) -> dict[str, list[dict]]:
    """Group workflows by each individual author/contributor.

    The "Author & contributor(s)" value can list several people (comma separated);
    a workflow is listed under every contributor so each person sees their own.
    Placeholder values (Unknown/Unassigned/etc.) collapse into one "Unassigned"
    bucket, matching how the web app treats unowned workflows.
    """
    groups: dict[str, list[dict]] = {}
    for item in items:
        raw = (item.get("author") or "").strip()
        contributors = [
            c.strip()
            for c in raw.split(",")
            if c.strip() and c.strip().lower() not in PLACEHOLDER_AUTHORS
        ] or [UNASSIGNED_LABEL]
        seen: set[str] = set()
        for contributor in contributors:
            canonical = NAME_ALIASES.get(contributor.lower(), contributor)
            if canonical in seen:  # avoid listing the same person twice for one workflow
                continue
            seen.add(canonical)
            groups.setdefault(canonical, []).append(item)
    return groups


def _sort_key(author: str) -> tuple[int, str]:
    # Push "Unassigned" / "Unknown" to the bottom; otherwise alphabetical.
    low = author.lower()
    is_unknown = low in {UNASSIGNED_LABEL.lower(), "unknown"}
    return (1 if is_unknown else 0, low)


def _author_sections(items: list[dict]) -> list[dict]:
    """One Slack section block per author group."""
    groups = group_by_author(items)
    sections: list[dict] = []
    for author in sorted(groups, key=_sort_key):
        group = groups[author]
        listed = group[:MAX_PER_AUTHOR]
        lines = [f"- <{w['url']}|{w['name']}>" for w in listed]
        remaining = len(group) - len(listed)
        if remaining > 0:
            lines.append(f"_...and {remaining} more_")
        sections.append(
            {
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"{mention(author)} ({len(group)})\n" + "\n".join(lines)},
            }
        )
    return sections


def _header(text: str) -> dict:
    return {"type": "header", "text": {"type": "plain_text", "text": text}}


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": text}}


def _context(page_url: str) -> dict:
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"<{page_url}|Open the Confluence tracker>"}],
    }


def _paginate(title: str, intro_blocks: list[dict], sections: list[dict], page_url: str, fallback: str) -> list[dict]:
    """Assemble one or more messages, chunking author sections to fit MAX_BLOCKS."""
    context = _context(page_url)
    capacity = MAX_BLOCKS - len(intro_blocks) - 1  # room for sections (minus context)
    capacity = max(1, capacity)

    if not sections:
        return [{"text": fallback, "blocks": [_header(title)] + intro_blocks + [context]}]

    messages: list[dict] = []
    for start in range(0, len(sections), capacity):
        chunk = sections[start : start + capacity]
        part = start // capacity + 1
        head_title = title if part == 1 else f"{title} (cont. {part})"
        head: list[dict] = [_header(head_title)]
        if part == 1:
            head += intro_blocks
        messages.append({"text": fallback, "blocks": head + chunk + [context]})
    return messages


def build_messages(stats: dict, pending: list[dict], missing_tags: list[dict], page_url: str) -> list[dict]:
    """Build the full list of Slack messages to post for this run."""
    messages: list[dict] = []

    # Message(s) 1: weekly status + pending info input.
    fallback = f"Dify workflows: {stats['total']} live, {stats['pending']} pending info input."
    summary = (
        f"*{stats['total']}* live workflows  |  "
        f"*{stats['pending']}* pending info input  |  "
        f"*{stats.get('missing_tags', 0)}* missing env tag  |  "
        f"*{stats['new']}* new this run  |  "
        f"*{stats['removed']}* removed from Dify"
    )
    if pending:
        intro = [_section(summary), {"type": "divider"}, _section("*Pending information input (by contributor):*")]
        messages += _paginate(
            f"{PROJECT_LABEL} - weekly status", intro, _author_sections(pending), page_url, fallback
        )
    else:
        intro = [_section(summary), _section(":white_check_mark: No workflows are pending information input.")]
        messages += _paginate(f"{PROJECT_LABEL} - weekly status", intro, [], page_url, fallback)

    # Message(s) 2: workflows missing an environment tag (prod/dev/test).
    if missing_tags:
        tag_fallback = f"{len(missing_tags)} workflows missing an environment tag (prod/dev/test)."
        intro = [
            _section(
                f"*{len(missing_tags)}* workflows have no environment tag "
                f"(need at least one of `prod`, `dev`, or `test`):"
            )
        ]
        messages += _paginate(
            "Missing environment tag", intro, _author_sections(missing_tags), page_url, tag_fallback
        )

    return messages


# Backwards-compatible single-message helper (status + pending only).
def build_message(stats: dict, pending: list[dict], page_url: str) -> dict:
    return build_messages(stats, pending, [], page_url)[0]


def build_deletion_messages(deleted: list[dict], failed: list[dict], page_url: str) -> list[dict]:
    """Build Slack message(s) announcing workflows deleted from Dify.

    :param deleted: list of {"name", "url"} successfully deleted
    :param failed: list of {"name", "url"} that could not be deleted
    """
    fallback = f"Deleted {len(deleted)} workflow(s) from Dify."
    intro = [
        _section(
            f":wastebasket: Deleted *{len(deleted)}* workflow(s) from Dify "
            f"(marked *Delete* in the tracker)."
        )
    ]
    if deleted:
        intro.append(
            _section(
                ":floppy_disk: A YAML backup of each deleted workflow is kept locally "
                "on the server (the trashcan folder)."
            )
        )
    sections: list[dict] = []
    if deleted:
        listed = deleted[:MAX_PER_AUTHOR * 2]
        # No links: the workflows are gone from Dify, so their URLs no longer resolve.
        lines = [f"- {w['name']}" for w in listed]
        remaining = len(deleted) - len(listed)
        if remaining > 0:
            lines.append(f"_...and {remaining} more_")
        sections.append(_section("\n".join(lines)))
    if failed:
        flines = [f"- <{w['url']}|{w['name']}>" for w in failed[: MAX_PER_AUTHOR * 2]]
        sections.append(_section(":warning: *Failed to delete:*\n" + "\n".join(flines)))
    return _paginate("Dify workflows deleted", intro, sections, page_url, fallback)


def post(message: dict) -> None:
    """Send a single payload to the Slack incoming webhook."""
    if not SLACK_WEBHOOK_URL:
        raise RuntimeError(
            "Missing SLACK_WEBHOOK_URL. Set it in .env (local) or as a GitHub Actions secret."
        )
    resp = httpx.post(SLACK_WEBHOOK_URL, json=message, timeout=30)
    resp.raise_for_status()


def post_all(messages: list[dict]) -> None:
    """Send several payloads in order."""
    for message in messages:
        post(message)
