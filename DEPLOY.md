# Run the Dify Workflow Console on the local server

A short guide to deploy the app with Docker on a local (Linux) server.

## Prerequisites

- A **Linux** host with **Docker** + **Docker Compose v2** (`docker compose version`).
- Network reachability to your **Dify** instance. If Dify is only reachable over a
  private network (e.g. NetBird/Tailscale), the host must be on that network.
  Quick check: `curl -sI https://<your-dify-host> | head -1`.
- A `.env` file with real credentials in the repo root (it is not in git).

## Steps

```bash
# 1. Get the code
git clone <repo-url>
cd dify-apps-dsl-exporter

# 2. Create the .env in the repo root:
#    cp .env.example .env  and fill in the values.
#    Make sure SESSION_SECRET is set to a long random string:
#    python3 -c "import secrets; print(secrets.token_urlsafe(48))"

# 3. Build and start
docker compose up -d --build

# 4. Open the app
#    http://<server-host>:3000
```

## Verify it's up

```bash
docker compose ps                                   # both services "running"
curl -s http://127.0.0.1:8008/api/health            # -> {"status":"ok"}
docker compose logs api | grep "Using Dify API"     # correct Dify origin, no stray text
```

Then log in with your **Dify** email + password.

## Everyday commands

```bash
docker compose logs -f          # follow logs
docker compose restart          # restart
docker compose down             # stop
docker compose up -d --build    # update after a git pull
```

## Notes

- **Networking**: compose uses host networking so the backend can resolve Dify
  over a private network (e.g. NetBird/Tailscale). This needs Linux (it won't
  work on Docker Desktop for macOS/Windows).
- **Data**: settings saved from the UI and job outputs live in the `appdata`
  Docker volume (`/app/data`). They survive restarts.
- **Admins**: prune / single-delete / settings / YAML export require an admin
  (Dify owner/admin role, or the allow-listed maintainer account).
- **Single instance only**: don't scale the `api` service — the job runner is
  in-memory.

## Troubleshooting

- **Login fails / dashboard empty** → backend can't reach Dify. Check
  `docker compose logs api` and confirm the network/DNS works from the host.
- **Can't open `:3000` from another machine** → check the host firewall allows
  ports 3000 (and 8008).
- **403 on prune/delete/settings** → your account isn't an admin.
