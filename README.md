# Dify Workflows DSL Exporter

A Python tool to export and import Dify workflows/apps as DSL (Domain-Specific Language) YAML files via the Dify console API. This helps teams back up, version control, and migrate workflows between Dify instances they can access.

## Quick Reference

```bash
# 1. Install Poetry (one-time setup)
curl -sSL https://install.python-poetry.org | python3 -
export PATH="$HOME/.local/bin:$PATH"

# 2. Setup project
git clone <repository-url>
cd dify-apps-dsl-exporter
poetry install

# 3. Configure credentials
cp .env.example .env
# Edit .env with your Dify credentials

# 4. Download/export all workflows from the configured Dify instance
poetry run python src/export.py

# 5. Upload/import all workflows from ./dsl into the configured Dify instance
poetry run python src/import.py
```

**Output**: All workflows are saved as YAML files in `./dsl/` directory.

## Features

- ✅ **Bulk Export**: Export all workflows from your Dify instance in one command
- ✅ **Bulk Import**: Import exported workflow YAML files into another Dify instance
- ✅ **Fast & Concurrent**: Uses async requests for fast downloads
- ✅ **Automatic Naming**: Files are named after your workflow titles
- ✅ **Duplicate Handling**: Automatically handles workflows with duplicate names
- ✅ **Cookie-based Auth**: Supports Dify's cookie-based authentication
- ✅ **Safe Secret Defaults**: Workflow secrets are not exported unless explicitly enabled
- ✅ **Error Handling**: Retries failed requests automatically

## Requirements

- **Python 3.10+**
- **Poetry** (for dependency management)

## Quick Start

### 1. Install Poetry (if not already installed)

```bash
# macOS/Linux
curl -sSL https://install.python-poetry.org | python3 -

# Add Poetry to your PATH (add to ~/.zshrc or ~/.bashrc)
export PATH="$HOME/.local/bin:$PATH"
```

### 2. Clone and Setup

```bash
# Clone the repository
git clone https://github.com/sattosan/dify-apps-dsl-exporter.git
cd dify-apps-dsl-exporter

# Install dependencies
poetry install
```

### 3. Configure Your Dify Credentials

Create a `.env` file in the project root:

```bash
cp .env.example .env
```

Edit `.env` with your Dify instance details:

```env
DIFY_ORIGIN=https://dify.example.com
EMAIL=your-email@example.com
PASSWORD=your-password
DSL_FOLDER_PATH=./dsl
DIFY_INCLUDE_SECRET=false
```

**Important Notes:**
- Remove any trailing slashes from `DIFY_ORIGIN` (e.g., use `https://dify.dctrl.ai` not `https://dify.dctrl.ai/`)
- For self-hosted instances, use your full URL (e.g., `http://localhost:3000`)
- For cloud instances, use the full domain (e.g., `https://api.dify.ai`)
- Keep `DIFY_INCLUDE_SECRET=false` for normal team sharing. Set it to `true` only if you intentionally need exported secret values in the YAML files.
- The tool uses Dify's `/console/api` email/password login flow. Instances that require SSO, MFA-only login, or a different auth flow may need code changes.

### 4. Download / Export All Workflows

```bash
# Make sure Poetry is in your PATH
export PATH="$HOME/.local/bin:$PATH"

# Run the export script
poetry run python src/export.py
```

The script will:
1. Authenticate with your Dify instance
2. Fetch all your workflows/applications
3. Download each workflow's DSL file as YAML
4. Save them to `DSL_FOLDER_PATH` (`./dsl` by default)

**Example Output:**
```
Login successful - using cookie-based authentication
Total apps: 25, Total pages: 1
Same name app count: 1, renamed list: ['openai_benchmark_rag -> 【same】openai_benchmark_rag-9c8c995f']
Starting to download YML files...
✅ Downloaded: ./dsl/Benchmarking-prod.yml
✅ Downloaded: ./dsl/demo_RAG.yml
...
```

## Output

All exported workflows are saved in the `./dsl/` directory as YAML files:

```
dsl/
├── Benchmarking-prod.yml
├── demo_RAG.yml
├── get_history.yml
└── ...
```

- Files are named after your workflow titles
- Duplicate names are automatically prefixed with `【same】` and an ID
- Each file contains the complete DSL definition of the workflow

## Additional Features

### Import / Upload Workflows

To import all workflows from `DSL_FOLDER_PATH` (`./dsl` by default) into the configured Dify instance:

```bash
poetry run python src/import.py
```

To import one workflow file:

```bash
poetry run python src/import.py ./dsl/my-workflow.yml
```

### Moving Workflows Between Dify Instances

1. Configure `.env` for the source Dify instance.
2. Run `poetry run python src/export.py`.
3. Review the YAML files from `DSL_FOLDER_PATH` and redact/rotate secrets before sharing.
4. Update `.env` for the target Dify instance.
5. Run `poetry run python src/import.py`.

### Delete Workflows

To delete a single workflow by its app ID (no bulk confirmation needed):

```bash
poetry run python src/delete.py <app_id>
```

⚠️ **Warning**: Running with no arguments deletes all workflows from your Dify instance. It is intentionally blocked unless you provide an explicit confirmation environment variable.

```bash
CONFIRM_DELETE_ALL=DELETE_ALL_WORKFLOWS \
poetry run python src/delete.py
```

## Confluence Tracker Sync + Slack Notification

`src/sync_tracker.py` keeps a Confluence "workflow tracker" page in sync with the
live Dify instance, then posts a status summary to Slack. It is designed to run
unattended on a schedule (see GitHub Actions below), but you can also run it manually.

What it does on each run:

1. Logs in to Dify and fetches every app with its metadata (author, created/updated dates, tags).
2. Reads the current Confluence tracker page (REST API, storage format).
3. Merges by **App ID**:
   - **Existing rows are preserved verbatim** so human-curated columns
     (`Working ?`, `Decision`, `Notes`, `Author & contributor(s)`, `Tags`) are never overwritten.
   - **New workflows** not yet on the page are appended with `Informations added ? = FALSE`
     and metadata pulled from Dify.
   - **Workflows removed from Dify** keep their row but get a red `Removed from Dify` status (history is preserved).
4. Writes the rebuilt page back (version + 1).
5. Posts Slack messages (grouped by contributor so each person sees their own):
   - **Weekly status** + workflows still **pending information input** (`Informations added ?` is not `TRUE`).
   - **Missing environment tag** - workflows whose `Tags` lack at least one of `prod` / `dev` / `test`.

   The two categories are sent as separate messages, and if a category is large its
   per-contributor sections are automatically chunked across additional messages to
   stay within Slack's 50-block-per-message limit.

### One-time setup

Add the following to `.env` (local runs) and as **GitHub Actions repository secrets** (scheduled runs):

| Variable | Notes |
| --- | --- |
| `CONFLUENCE_BASE_URL` | e.g. `https://1dev.atlassian.net/wiki` (include `/wiki`) |
| `CONFLUENCE_EMAIL` | Atlassian account email that owns the API token |
| `CONFLUENCE_API_TOKEN` | Create at https://id.atlassian.com/manage-profile/security/api-tokens |
| `CONFLUENCE_PAGE_ID` | Numeric id of the tracker page (e.g. `407797761`) |
| `SLACK_WEBHOOK_URL` | A Slack incoming webhook URL for the target channel |

For the GitHub Action the Dify credentials are read from secrets named
`DIFY_ORIGIN`, `DIFY_EMAIL`, and `DIFY_PASSWORD`.

### Run it manually

```bash
# venv runner (installs: httpx python-dotenv beautifulsoup4)
./run.sh sync              # update Confluence + post to Slack
./run.sh sync --dry-run    # compute and print only; change nothing
./run.sh sync --no-slack   # update Confluence but skip Slack

# or with Poetry
poetry run python src/sync_tracker.py --dry-run
```

### Pruning workflows marked "Delete"

`src/prune_deleted.py` deletes every workflow whose `Decision` column on the tracker is
`Delete` (and that still exists in Dify), moves each deleted workflow's exported YAML
into a trashcan folder, then flags those rows red `Removed from Dify` on the page and
posts a Slack deletion notice. Deletion is permanent, so it is gated behind an explicit
flag.

The trashcan folder defaults to a sibling of `DSL_FOLDER_PATH` (e.g.
`./dify-pelonis-workflows` → `./dify-pelonis-trashcan`); override it with
`DSL_TRASHCAN_PATH`. It is git-ignored like the export folders.

```bash
./run.sh prune            # list candidates only (safe, no deletion)
./run.sh prune --yes      # delete + flag Confluence + notify Slack
./run.sh prune --yes --no-slack
```

This is intentionally a manual step and is NOT part of the weekly schedule.

## Web app (console UI)

In addition to the CLI, the project ships a small web app: a **FastAPI** backend
(`src/api`) that wraps the existing modules, and a **Next.js** frontend (`frontend/`).
It lets the team trigger the actions (sync / env tags / export / prune) from the
browser and watch them run live, plus a governance dashboard of every workflow
(author, env tags, decision, pending/missing-env status) sourced live from Dify +
Confluence.

- **Auth**: log in with your existing Dify credentials. Your Dify workspace role is
  resolved automatically; destructive actions (prune) require an `owner`/`admin` role.
- **Jobs**: actions run one-at-a-time on the backend (they share the Confluence page,
  so they must not overlap) with their logs streamed to the UI. Prune always offers a
  dry-run preview and requires typing `DELETE` to confirm.

### Run it locally

```bash
# one-time: install backend + frontend deps
./venv/bin/pip install -e . || ./venv/bin/pip install fastapi "uvicorn[standard]" itsdangerous
(cd frontend && npm install)

# start both (backend on :8008, frontend on :3000)
./dev.sh
# then open http://localhost:3000
```

Or run the two processes separately:

```bash
./run.sh serve                 # backend only (uvicorn, :8008, --reload)
(cd frontend && npm run dev)    # frontend only (:3000)
```

Add `SESSION_SECRET` (and optionally `ADMIN_ROLES` / `ADMIN_EMAILS`) to `.env` —
see `.env.example`. All Dify/Confluence/Slack operations run as the service account
configured in `.env`; the per-user login only controls access and role gating.

Not yet included (planned later phases): persistent job history, in-app workflow
health/analysis, and live Dify execution/runtime monitoring.

### Deploy on a local server (Docker)

The app ships with a `docker-compose.yml` that builds two images — the FastAPI
backend (`Dockerfile.api`) and the Next.js frontend (`frontend/Dockerfile`, built
to a standalone server).

```bash
cp .env.example .env       # fill in real values; set a strong SESSION_SECRET
docker compose up -d --build
# open http://<server-host>:3000
```

Notes:

- **Host networking** is used so the backend can resolve/reach Dify over your
  Tailnet (MagicDNS names resolve via the host's `tailscaled`). This requires a
  **Linux host**; Docker Desktop on macOS/Windows does not support
  `network_mode: host`.
  - Bridge alternative (only if the server reaches Dify via normal DNS/routing):
    remove the two `network_mode: host` lines, add `ports: ["8008:8008"]` to
    `api` and `ports: ["3000:3000"]` to `web`, and set the `web` build arg +
    env `BACKEND_URL=http://api:8008`.
- **Persistence**: the `appdata` volume holds the UI settings overlay
  (`/app/data/settings.json`) and job outputs (`/app/data/dsl`, `…/readable`,
  and the sibling trashcan). Don't run more than one `api` replica — the job
  runner is in-memory/single-worker.
- **HTTPS**: for plain-HTTP LAN access the defaults are fine. Behind a TLS
  reverse proxy, set `https_only=True` on the session cookie in `src/api/app.py`
  and point `FRONTEND_ORIGINS` at the HTTPS URL.

## Readable Markdown reports

Dify DSL exports are built for the Dify editor, not for humans: node IDs are opaque
timestamps, the graph is a flat list of nodes + edges, and variable references look like
`{{#1752536193945.topic#}}`. The `readable` command turns each DSL into a Markdown report
that is easy to read and review:

- app header (name, mode, description) and a node-type summary,
- a **Mermaid flowchart** of the graph (renders on GitHub / Confluence / VS Code), with
  iterations and loops shown as subgraphs,
- a node-by-node breakdown showing the meaningful config per node type (LLM model + prompts,
  code, HTTP method/URL/body, if-else conditions, tool + parameters, iteration selectors, ...),
- every opaque node ID rewritten to the node's **title**, so a reference reads
  `{{Topic+subprompt.topic}}` instead of `{{#1752536193945.topic#}}`. References that cannot
  be resolved are left raw on purpose, which surfaces broken references in the original flow.

```bash
./run.sh readable                       # convert every workflow in DSL_FOLDER_PATH
./run.sh readable path/to/flow.yml      # convert a single file
./run.sh readable some/dir --out docs   # convert a folder into ./docs
```

Reports are written to `./dify-pelonis-readable/` (override with `READABLE_FOLDER_PATH` or
`--out`), one `.md` per workflow plus a `README.md` index. Because the reports embed the same
prompts/code as the DSL, the output folder is gitignored by default.

### Publishing to Confluence

`--output confluence` creates/updates one Confluence page per workflow (plus an index page)
inside a target folder, instead of writing local Markdown. The Markdown is rendered to
Confluence storage format: code and prompts become collapsible code macros.

Confluence has no native Mermaid support, so the flow diagram is **rendered to an image via
[Kroki](https://kroki.io)** and uploaded as a page attachment (shown inline), with the Mermaid
source kept in a collapsible block for editing. Use `--diagrams code` to skip image rendering
and embed the raw Mermaid source as a code block instead.

```bash
./run.sh readable --output confluence                       # all workflows -> default folder
./run.sh readable --output confluence --space SIC --parent-id 423952430
./run.sh readable --output confluence --diagrams code        # no image rendering
```

By default diagrams are rendered by the public `kroki.io`. For privacy (diagram text never
leaves your network) or speed, run Kroki locally and point `KROKI_URL` at it. Mermaid needs
Kroki's companion service, so start both:

```bash
docker run -d --name kroki-mermaid yuzutech/kroki-mermaid
docker run -d --name kroki -p 8000:8000 --link kroki-mermaid \
  -e KROKI_MERMAID_HOST=kroki-mermaid yuzutech/kroki
KROKI_URL=http://localhost:8000 ./run.sh readable --output confluence
```

Diagram rendering is configurable via `KROKI_URL`, `KROKI_FORMAT` (`svg` default, or `png`),
and `KROKI_TIMEOUT` (seconds; a slow render falls back to a Mermaid code block).

- An **index page** ("Dify Workflows — Index") is created under the
  **"Dify workflows documentation"** folder (`SIC` space, id `423952430` by default; override
  with `--parent-id` / `--space` or the `CONFLUENCE_DOCS_PARENT_ID` / `CONFLUENCE_DOCS_SPACE`
  env vars), and each **workflow doc is a sub-page of that index**.
- The index lists **every** doc page (not just the ones in the current run), so publishing a
  single workflow refreshes its page without shrinking the index.
- Each doc page includes an **"Open in Dify"** link to the live workflow (resolved from the
  Dify app list; requires reaching the Dify console, otherwise the link is skipped). A
  `confluence_links.md` mapping is also written to the output folder.
- Runs are **idempotent**: a page is matched by title and updated in place, so re-running
  refreshes the docs rather than creating duplicates. Workflows that share an app name are
  disambiguated by appending the source filename.
- Uses the same `CONFLUENCE_BASE_URL` / `CONFLUENCE_EMAIL` / `CONFLUENCE_API_TOKEN` credentials
  as the tracker sync.

### Scheduled runs (GitHub Actions)

`.github/workflows/sync-tracker.yml` runs the sync **weekly (Mondays 08:00 UTC)** and
exposes a manual **Run workflow** button (with `dry_run` / `no_slack` toggles). After adding
the secrets above, no further setup is required.

> If your Dify host is only reachable on a private network, GitHub-hosted runners will not
> reach it. In that case run `./run.sh sync` from a machine on that network via `cron`
> (e.g. `0 8 * * 1 /path/to/dify-apps-dsl-exporter/run.sh sync`) or a self-hosted runner.

## Troubleshooting

### Poetry Command Not Found

If you get `command not found: poetry`, add Poetry to your PATH:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

Or add it permanently to your shell config (`~/.zshrc` or `~/.bashrc`):

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

### Authentication Errors (401 Unauthorized)

- **Check your credentials**: Verify your email and password in `.env`
- **Check the URL**: Ensure `DIFY_ORIGIN` is correct and has no trailing slash
- **Check API access**: For self-hosted instances, ensure API access is enabled

### No Workflows Found

- Verify you have workflows in your Dify instance
- Check that your account has access to the workflows
- Ensure the Dify instance URL is correct

### Connection Errors

- Verify your Dify instance is accessible
- Check network connectivity
- For self-hosted instances, ensure the server is running

## How It Works

1. **Authentication**: The script logs in to Dify using your credentials and receives session cookies
2. **Token Extraction**: Extracts the JWT access token from cookies for API authentication
3. **Pagination**: Fetches all workflows using paginated API requests
4. **Concurrent Downloads**: Downloads DSL files concurrently (up to 3 at a time) for speed
5. **File Naming**: Sanitizes workflow names for filesystem compatibility

## Project Structure

```
dify-apps-dsl-exporter/
├── src/
│   ├── export.py        # Main export script
│   ├── import.py        # Import workflows script
│   ├── delete.py        # Delete workflows script
│   ├── dify_api.py      # Dify API client
│   ├── confluence.py    # Confluence REST v2 client + storage helpers
│   ├── slack_notify.py  # Slack incoming-webhook status message
│   ├── sync_tracker.py  # Weekly Confluence sync + Slack notification
│   └── prune_deleted.py # Delete tracker "Delete"-marked workflows + notify
├── .github/workflows/
│   └── sync-tracker.yml # Scheduled (weekly) + manual tracker sync
├── run.sh               # Convenience runner (export|import|delete|sync)
├── dsl/                 # Exported workflow files (created after export by default)
├── .env                 # Your credentials (create from .env.example)
├── .env.example         # Example configuration file
├── pyproject.toml       # Poetry dependencies
└── README.md            # This file
```

## Security Notes

- **Never commit `.env`**: The `.env` file contains your credentials and should be in `.gitignore`
- **Secrets are excluded by default**: `DIFY_INCLUDE_SECRET=false` avoids exporting workflow secret values
- **Review YAML before sharing**: If you ever export with `DIFY_INCLUDE_SECRET=true`, rotate or remove secrets before sharing
- **Generated folders are ignored by default**: `dsl/` is ignored to avoid accidental commits. Share or version workflow YAML only after reviewing/redacting it.
- **Keep credentials secure**: Share credentials only through secure channels
- **Use environment variables**: For CI/CD, consider using environment variables instead of `.env` files

## Contributing

This is a community-maintained tool. Contributions are welcome!

## License

See the repository for license information.

## Sharing with Your Team

To share this tool with your team:

1. **Share the repository**: Clone or fork this repository
2. **Each team member sets up their own `.env`**: 
   - Each person should create their own `.env` file with their credentials
   - Never commit `.env` files to version control
3. **Quick setup for team members**:
   ```bash
   git clone <repository-url>
   cd dify-apps-dsl-exporter
   poetry install
   cp .env.example .env
   # Edit .env with their credentials

   # Download workflows from the configured instance
   poetry run python src/export.py

   # Upload workflows from DSL_FOLDER_PATH to the configured instance
   poetry run python src/import.py
   ```

### Team Workflow

1. **Export workflows** from the source Dify instance.
2. **Review the YAML files** before sharing, especially if secrets were intentionally included.
3. **Version control reviewed DSL files intentionally** if you want history and review; do not commit raw exports blindly.
4. **Import workflows** into the target Dify instance using each team member's own `.env`.

## Support

For issues or questions:
- Check the troubleshooting section above
- Review the error messages for specific guidance
- Open an issue on the GitHub repository
