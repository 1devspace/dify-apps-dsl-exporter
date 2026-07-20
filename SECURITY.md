# Security Policy

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

Instead, use GitHub's private reporting: **Security → Advisories → Report a
vulnerability** on this repository. If that is unavailable, open a minimal issue
asking a maintainer to contact you privately (without disclosing details).

Include where relevant:

- a description of the issue and its impact,
- steps to reproduce or a proof of concept,
- affected version/commit and configuration.

We aim to acknowledge reports within a few business days and will coordinate a fix
and disclosure timeline with you.

## Scope and handling of secrets

This tool talks to Dify, Confluence, and Slack using credentials you provide. Keep the
following in mind:

- **Never commit secrets.** All credentials live in `.env` (git-ignored) or your
  secrets manager. `.env.example` contains placeholders only.
- **Exports can contain secrets.** `DIFY_INCLUDE_SECRET=true` writes workflow secret
  values into the exported YAML. Keep it `false` unless you deliberately need them, and
  review/redact before sharing. Generated folders (`dsl/`, `*-trashcan/`, `*-readable/`)
  are git-ignored by default.
- **The web console holds credentials.** It acts as the service account in `.env`, signs
  sessions with `SESSION_SECRET`, and stores runtime settings in `data/settings.json`
  (git-ignored). Generate a strong `SESSION_SECRET` and restrict who has the admin role.
- **Rotate anything that leaks.** If a credential is exposed, revoke/rotate it at the
  source (Dify, Atlassian API token, Slack webhook) immediately.

If you find secrets committed to history or leaking through the app, please report it
via the process above.
