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
- **Publish** copies `entries.json` to `published.json` and renders `index.html` into `./site`.
- Totals accrue daily, so the editor re-renders `index.html` from `published.json` once a day. Unpublished edits never leak out this way.
- nginx serves `/` only. Everything else returns 404. Notes and the data file are never in the page.

## Deploy (Portainer, Ubuntu)

Every push to `master` runs the tests, then GitHub Actions builds both images and pushes them to GHCR (`ghcr.io/davidgascon/savingsreport-editor` and `-public`). The server only pulls; nothing is built there.

1. In Portainer: **Stacks → Add stack**. Either paste `docker-compose.yml` into the **Web editor**, or use **Repository** pointed at this repo (reference `refs/heads/master`, compose path `docker-compose.yml`).
2. Set the stack environment variables (optional):

   | Variable | Default | Purpose |
   | --- | --- | --- |
   | `TZ` | `America/Los_Angeles` | Pacific time (WA). "Today" rolls over at local midnight |
   | `ADMIN_BIND` | `0.0.0.0` | Set to the server's LAN IP to bind the editor to that interface only |

3. Deploy, open `http://<server>:8086`, and click **Publish** once.

   Data lives in `./data` and the built page in `./site`, next to `docker-compose.yml`. Docker creates both on first start. Back up `./data`.
   With a Portainer CE Repository stack, "next to the compose file" is Portainer's checkout folder (`/data/compose/<stack id>/` on the host), not a folder you chose. If you want the data somewhere predictable, run the stack from a clone instead (below).
4. In OPNsense, forward 8085 only, or put it behind nginx Proxy Manager for TLS. Never forward 8086. Docker-published ports bypass ufw, so rely on OPNsense (or `ADMIN_BIND`) rather than ufw to keep 8086 on the LAN.

Or run it from a clone on the server, so `./data` is wherever you cloned it:

```bash
git clone https://github.com/davidgascon/SavingsReport.git /opt/savings-report
cd /opt/savings-report && docker compose up -d
```

To update the app in Portainer, re-pull the images: **Stacks → savings-report → Editor → Update the stack** with **Re-pull image** on.

Portainer will list a clone-run stack as "limited" (it can't redeploy it), but it still runs. To update: `git pull && docker compose pull && docker compose up -d`.

## Develop

```bash
python -m venv .venv
.venv/Scripts/python -m pip install pytest fastapi uvicorn httpx
.venv/Scripts/python -m pytest
DATA_DIR=./data SITE_DIR=./site .venv/Scripts/python -m uvicorn app.main:app --port 8086
```

The preview is at `/preview`.
