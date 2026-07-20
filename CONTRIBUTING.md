# Contributing

Thanks for your interest in improving this project! Bug reports, feature ideas, and
pull requests are all welcome.

## Ground rules

- Be respectful and constructive.
- Never include real credentials, tokens, internal hostnames, or exported workflow
  YAML in issues, PRs, or commits. Use placeholders.
- By contributing, you agree your contributions are licensed under the project's
  [MIT License](LICENSE).

## Reporting bugs / requesting features

Open a GitHub issue with:

- what you expected vs. what happened (and steps to reproduce), or
- the problem a feature would solve and a rough sketch of the behavior.

For security issues, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.

## Development setup

Backend (Python 3.10+):

```bash
git clone https://github.com/1devspace/dify-console.git
cd dify-console
poetry install            # or: python -m venv venv && venv/bin/pip install -r requirements.txt
cp .env.example .env       # fill in your own Dify/Confluence/Slack values
```

Web console (optional — Node 20+):

```bash
(cd frontend && npm install)
./dev.sh                   # backend on :8008, frontend on :3000
```

See the README for the full CLI and web-app usage.

## Making changes

1. Create a branch off the default branch (e.g. `feat/<short-name>` or `fix/<short-name>`).
2. Keep changes focused; match the existing code style.
3. Do a quick manual check of what you touched (run the relevant CLI command or the app).
4. Update the README/`.env.example` when you add or change configuration or behavior.
5. Open a PR describing the change, the motivation, and how you tested it.

## Commit / PR notes

- Keep secrets out of diffs; confirm nothing sensitive is staged before committing.
- Small, reviewable PRs are preferred over large ones.
