"""Runtime configuration store for the web app's Settings tab.

Configuration normally comes from environment variables / ``.env``. This module
adds a small JSON overlay (``data/settings.json`` by default) so the values can
be edited from the UI without touching files on the server by hand.

Precedence (highest first):
    1. ``data/settings.json`` (written by the Settings tab)
    2. process environment / ``.env``
    3. built-in defaults in :data:`SCHEMA`

The overlay is applied onto ``os.environ`` at startup (before the CLI modules
that cache config at import time are loaded) and again whenever settings are
saved, after which the affected modules are asked to re-read their config via
their ``refresh()`` hooks.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
STORE_PATH = Path(os.getenv("SETTINGS_FILE") or (REPO_ROOT / "data" / "settings.json"))

# type: "text" | "password" | "bool"
# Only the essential connection settings are editable from the UI. Advanced
# options (docs space/parent, export & readable folders, Kroki URL, admin
# roles/emails, include-secret toggle) remain configurable via .env.
SCHEMA: list[dict[str, Any]] = [
    # --- Dify ---
    {"key": "DIFY_ORIGIN", "label": "Dify origin URL", "group": "Dify", "type": "text",
     "help": "Base URL of your Dify instance, e.g. http://localhost or https://dify.example.com."},
    {"key": "EMAIL", "label": "Dify email", "group": "Dify", "type": "text",
     "help": "Service account email used for all Dify API calls."},
    {"key": "PASSWORD", "label": "Dify password", "group": "Dify", "type": "password",
     "secret": True, "help": "Password for the Dify service account."},

    # --- Confluence ---
    {"key": "CONFLUENCE_BASE_URL", "label": "Confluence base URL", "group": "Confluence",
     "type": "text", "help": "Confluence Cloud base URL including the /wiki suffix."},
    {"key": "CONFLUENCE_EMAIL", "label": "Atlassian email", "group": "Confluence", "type": "text",
     "help": "Atlassian account email that owns the API token."},
    {"key": "CONFLUENCE_API_TOKEN", "label": "Confluence API token", "group": "Confluence",
     "type": "password", "secret": True,
     "help": "Create at id.atlassian.com/manage-profile/security/api-tokens."},
    {"key": "CONFLUENCE_PAGE_ID", "label": "Tracker page ID", "group": "Confluence", "type": "text",
     "help": "Numeric id of the Confluence tracker page kept in sync."},

    # --- Slack ---
    {"key": "SLACK_WEBHOOK_URL", "label": "Slack webhook URL", "group": "Slack", "type": "password",
     "secret": True, "help": "Incoming webhook for the channel that receives status messages."},
]

_BY_KEY = {f["key"]: f for f in SCHEMA}
SECRET_KEYS = {f["key"] for f in SCHEMA if f.get("secret")}
SECRET_MASK = "********"


def _read_store() -> dict[str, str]:
    try:
        with open(STORE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        return {k: v for k, v in data.items() if isinstance(k, str)}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _write_store(values: dict[str, str]) -> None:
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STORE_PATH, "w", encoding="utf-8") as fh:
        json.dump(values, fh, indent=2, sort_keys=True)
        fh.write("\n")


def apply_to_env() -> None:
    """Overlay stored settings onto ``os.environ`` (store wins over .env)."""
    for key, value in _read_store().items():
        if key in _BY_KEY and value is not None and str(value) != "":
            os.environ[key] = str(value)


def reload_runtime_config() -> None:
    """Re-apply settings and ask already-imported modules to re-read config."""
    apply_to_env()
    for mod_name in ("confluence", "dify_api", "slack_notify"):
        mod = __import__(mod_name)
        refresh = getattr(mod, "refresh", None)
        if callable(refresh):
            refresh()


def effective_value(key: str) -> str:
    field = _BY_KEY[key]
    return os.environ.get(key, str(field.get("default", "")) or "")


def public_settings() -> dict[str, Any]:
    """Schema + current values for the UI. Secrets are masked, never returned."""
    groups: list[dict[str, Any]] = []
    by_group: dict[str, dict[str, Any]] = {}
    for field in SCHEMA:
        g = field["group"]
        if g not in by_group:
            by_group[g] = {"group": g, "fields": []}
            groups.append(by_group[g])
        is_secret = bool(field.get("secret"))
        current = effective_value(field["key"])
        by_group[g]["fields"].append(
            {
                "key": field["key"],
                "label": field["label"],
                "type": field["type"],
                "help": field.get("help", ""),
                "secret": is_secret,
                "is_set": bool(current),
                # Secrets are never sent to the client; only whether one is set.
                "value": "" if is_secret else current,
            }
        )
    return {"groups": groups}


def update(values: dict[str, Any]) -> None:
    """Merge submitted values into the store and re-apply them.

    For secret fields, an empty/placeholder value means "keep the existing one".
    """
    store = _read_store()
    for key, value in values.items():
        if key not in _BY_KEY:
            continue
        field = _BY_KEY[key]
        if field["type"] == "bool":
            store[key] = "true" if value in (True, "true", "1", "yes", "on") else "false"
            continue
        text = "" if value is None else str(value)
        if field.get("secret") and (text == "" or text == SECRET_MASK):
            continue  # leave the stored secret untouched
        store[key] = text
    _write_store(store)
    reload_runtime_config()
