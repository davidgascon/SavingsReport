# Homelab Savings Report

Is the server rack ahead or behind financially? A LAN-only editor (port 8086) holds the entries and publishes a self-contained static page served on a public port (8085). See [SPEC.md](SPEC.md) for the full spec.

```
app/
  calc.py            accrual + electricity math (stdlib only)
  build.py           renders the public page from calc output
  store.py           JSON data file, atomic writes
  main.py            FastAPI editor: API, preview, publish, daily refresh
  static/editor.html editor UI
  templates/public.html public page template (inline CSS/JS, no external calls)
public/              nginx image that serves only index.html
tests/               pytest: calc rules + API
```

## How publishing works

- The editor writes `entries.json`. Nothing public changes until you click **Publish**.
- **Publish** copies `entries.json` to `published.json` and renders `index.html` into the `site` volume.
- Totals accrue daily, so the editor re-renders `index.html` from `published.json` once a day. Unpublished edits never leak out this way.
- nginx serves `/` only. Everything else returns 404. Notes and the data file are never in the page.

## Deploy (Portainer, Ubuntu)

1. Push this repo to GitHub or Gitea.
2. In Portainer: **Stacks → Add stack → Repository**. Point it at the repo, compose path `docker-compose.yml`. Add a deploy key or token if the repo is private.
3. Set the stack environment variables:

   | Variable | Default | Purpose |
   | --- | --- | --- |
   | `TZ` | `UTC` | Your zone, e.g. `America/New_York`, so "today" rolls over at local midnight |
   | `DATA_PATH` | `/opt/savings-report/data` | Host folder for `entries.json` and `published.json`. Add it to your backups |
   | `ADMIN_BIND` | `0.0.0.0` | Set to the server's LAN IP to bind the editor to that interface only |

4. Deploy, open `http://<server>:8086`, and click **Publish** once.
5. In OPNsense, forward 8085 only, or put it behind nginx Proxy Manager for TLS. Never forward 8086. Docker-published ports bypass ufw, so rely on OPNsense (or `ADMIN_BIND`) rather than ufw to keep 8086 on the LAN.

Without a git remote, you can also run it straight on the server:

```bash
docker compose up -d --build
```

Portainer will list that stack as "limited" (it can't redeploy it), but it still runs.

## Develop

```bash
python -m venv .venv
.venv/Scripts/python -m pip install pytest fastapi uvicorn httpx
.venv/Scripts/python -m pytest
DATA_DIR=./data SITE_DIR=./site .venv/Scripts/python -m uvicorn app.main:app --port 8086
```

The preview is at `/preview`.
