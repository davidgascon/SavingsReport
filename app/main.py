"""LAN-only editor: owns the data file, previews, and publishes the static page.

SPEC.md: Editor features. Runs on the admin port (8086); the public port only
ever sees the HTML file this app writes into SITE_DIR.
"""
from __future__ import annotations

import asyncio
import copy
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field, field_validator
from typing_extensions import Literal

from . import build, calc, store

DATA_DIR = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "data"))
SITE_DIR = os.environ.get("SITE_DIR", os.path.join(os.path.dirname(__file__), "..", "site"))
DATA_FILE = os.path.join(DATA_DIR, "entries.json")
PUBLISHED_FILE = os.path.join(DATA_DIR, "published.json")
SITE_FILE = os.path.join(SITE_DIR, "index.html")
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
REFRESH_SECONDS = 15 * 60

_state = {"last_build_date": None}


def today() -> date:
    tz = os.environ.get("TZ")
    if tz:
        try:
            from zoneinfo import ZoneInfo
            return datetime.now(ZoneInfo(tz)).date()
        except Exception:
            pass
    return date.today()


# --- Models ------------------------------------------------------------------

class EntryIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    direction: Literal["expense", "savings"]
    frequency: Literal["one_time", "monthly"]
    amount: float = Field(gt=0)
    start_date: date
    end_date: Optional[date] = None
    category: str
    beneficiary: str = calc.ME
    notes: Optional[str] = Field(default=None, max_length=2000)

    @field_validator("name", "category", "beneficiary")
    @classmethod
    def strip(cls, v):
        v = v.strip()
        if not v:
            raise ValueError("must not be blank")
        return v


class EndIn(BaseModel):
    end_date: Optional[date] = None


class ReadingIn(BaseModel):
    date: Optional[date] = None
    watts: float = Field(gt=0)
    note: Optional[str] = Field(default=None, max_length=500)


class RateIn(BaseModel):
    effective_date: date
    rate_per_kwh: float = Field(gt=0)


class SettingsIn(BaseModel):
    rack_online_since: Optional[date] = None


class ListsIn(BaseModel):
    categories: List[str]
    people: List[str]


# --- Helpers -----------------------------------------------------------------

def _load() -> dict:
    return store.load(DATA_FILE)


def _save(data: dict) -> dict:
    store.save(DATA_FILE, data)
    return data


def _iso(d):
    return d.isoformat() if d else None


def _entry_record(body: EntryIn, data: dict, entry_id: str) -> dict:
    if body.category not in data["categories"]:
        raise HTTPException(400, "Unknown category %r. Add it under Lists first." % body.category)
    if body.beneficiary not in data["people"]:
        raise HTTPException(400, "Unknown person %r. Add it under Lists first." % body.beneficiary)
    if body.end_date and body.frequency != "monthly":
        raise HTTPException(400, "Only monthly entries have an end date.")
    if body.end_date and body.end_date < body.start_date:
        raise HTTPException(400, "End date is before the start date.")
    return {
        "id": entry_id,
        "name": body.name,
        "direction": body.direction,
        "frequency": body.frequency,
        "amount": body.amount,
        "start_date": body.start_date.isoformat(),
        "end_date": _iso(body.end_date),
        "category": body.category,
        "beneficiary": body.beneficiary,
        "notes": (body.notes or "").strip() or None,
    }


def _find(rows: list, row_id: str) -> int:
    for i, row in enumerate(rows):
        if row.get("id") == row_id:
            return i
    raise HTTPException(404, "Not found")


def _clean_list(values: List[str]) -> List[str]:
    out = []
    for v in values:
        v = v.strip()
        if v and v not in out:
            out.append(v)
    return out


def rebuild_public() -> None:
    """Rebuild the public page from the last published snapshot.

    Totals accrue daily, so the page is re-rendered each day from the snapshot,
    which never picks up unpublished edits.
    """
    if os.path.exists(PUBLISHED_FILE):
        html = build.render(store.load(PUBLISHED_FILE), today())
    else:
        html = build.render(copy.deepcopy(store.DEFAULT_DATA), today())
    store.write_text(SITE_FILE, html)
    _state["last_build_date"] = today()


async def _refresh_loop():
    while True:
        try:
            if _state["last_build_date"] != today() or not os.path.exists(SITE_FILE):
                rebuild_public()
        except Exception as exc:  # keep the loop alive; the next tick retries
            print("refresh failed:", exc, flush=True)
        await asyncio.sleep(REFRESH_SECONDS)


# --- App ---------------------------------------------------------------------

@asynccontextmanager
async def lifespan(_app):
    task = asyncio.ensure_future(_refresh_loop())
    yield
    task.cancel()


app = FastAPI(title="Homelab Savings Editor", docs_url=None, redoc_url=None, lifespan=lifespan)


@app.get("/", include_in_schema=False)
def editor():
    return FileResponse(os.path.join(STATIC_DIR, "editor.html"), headers={"Cache-Control": "no-store"})


@app.get("/preview", response_class=HTMLResponse, include_in_schema=False)
def preview():
    return build.render(_load(), today(), preview=True)


@app.get("/api/data")
def get_data():
    return _load()


@app.get("/api/status")
def status():
    data = _load()
    published = store.load(PUBLISHED_FILE) if os.path.exists(PUBLISHED_FILE) else None
    published_at = None
    if published is not None:
        published_at = datetime.fromtimestamp(os.path.getmtime(PUBLISHED_FILE), timezone.utc).isoformat()
    summaries = {view: calc.summarize(data, today(), view) for view in calc.VIEWS}
    return {
        "today": today().isoformat(),
        "published_at": published_at,
        "unpublished_changes": published != data,
        "summary": {view: _headline(s) for view, s in summaries.items()},
        "to_date": {r["id"]: r["to_date"] for r in summaries["everyone"]["entries"]},
    }


def _headline(s: dict) -> dict:
    return {k: s[k] for k in ("net", "saved", "spent", "run_rate", "break_even")}


# Entries

@app.post("/api/entries", status_code=201)
def add_entry(body: EntryIn):
    data = _load()
    record = _entry_record(body, data, store.new_id())
    data["entries"].append(record)
    _save(data)
    return record


@app.put("/api/entries/{entry_id}")
def update_entry(entry_id: str, body: EntryIn):
    data = _load()
    i = _find(data["entries"], entry_id)
    data["entries"][i] = _entry_record(body, data, entry_id)
    _save(data)
    return data["entries"][i]


@app.post("/api/entries/{entry_id}/end")
def end_entry(entry_id: str, body: EndIn):
    data = _load()
    entry = data["entries"][_find(data["entries"], entry_id)]
    if entry["frequency"] != "monthly":
        raise HTTPException(400, "Only monthly entries can be ended.")
    end = body.end_date or today()
    if end < calc.parse_date(entry["start_date"]):
        raise HTTPException(400, "End date is before the start date.")
    entry["end_date"] = end.isoformat()
    _save(data)
    return entry


@app.delete("/api/entries/{entry_id}", status_code=204)
def delete_entry(entry_id: str):
    data = _load()
    del data["entries"][_find(data["entries"], entry_id)]
    _save(data)


# Electricity

@app.post("/api/readings", status_code=201)
def add_reading(body: ReadingIn):
    data = _load()
    record = {
        "id": store.new_id(),
        "date": (body.date or today()).isoformat(),
        "watts": body.watts,
        "note": (body.note or "").strip() or None,
    }
    data["power_readings"].append(record)
    data["power_readings"].sort(key=lambda r: r["date"])
    _save(data)
    return record


@app.delete("/api/readings/{reading_id}", status_code=204)
def delete_reading(reading_id: str):
    data = _load()
    del data["power_readings"][_find(data["power_readings"], reading_id)]
    _save(data)


@app.post("/api/rates", status_code=201)
def add_rate(body: RateIn):
    data = _load()
    record = {"id": store.new_id(), "effective_date": body.effective_date.isoformat(), "rate_per_kwh": body.rate_per_kwh}
    data["rates"].append(record)
    data["rates"].sort(key=lambda r: r["effective_date"])
    _save(data)
    return record


@app.delete("/api/rates/{rate_id}", status_code=204)
def delete_rate(rate_id: str):
    data = _load()
    del data["rates"][_find(data["rates"], rate_id)]
    _save(data)


@app.put("/api/settings")
def update_settings(body: SettingsIn):
    data = _load()
    data["settings"]["rack_online_since"] = _iso(body.rack_online_since)
    _save(data)
    return data["settings"]


# Lists

@app.put("/api/lists")
def update_lists(body: ListsIn):
    data = _load()
    categories = _clean_list(body.categories)
    people = _clean_list(body.people)
    if calc.ME not in people:
        raise HTTPException(400, "The people list must keep %r." % calc.ME)
    if not categories:
        raise HTTPException(400, "Keep at least one category.")
    used_cats = sorted({e["category"] for e in data["entries"]} - set(categories))
    used_people = sorted({e.get("beneficiary", calc.ME) for e in data["entries"]} - set(people))
    if used_cats or used_people:
        raise HTTPException(400, "Still used by entries: %s" % ", ".join(used_cats + used_people))
    data["categories"] = categories
    data["people"] = people
    _save(data)
    return {"categories": categories, "people": people}


# Publish

@app.post("/api/publish")
def publish():
    store.save(PUBLISHED_FILE, _load())
    rebuild_public()
    return status()
