import io
import json
import os
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import main

TODAY = date(2026, 10, 11)

APPLE = {
    "name": "Apple TV+",
    "direction": "savings",
    "frequency": "monthly",
    "amount": 10.74,
    "start_date": "2026-01-04",
    "category": "Subscriptions",
    "beneficiary": "Me",
    "notes": "SECRET-NOTE",
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    data_dir, site_dir = tmp_path / "data", tmp_path / "site"
    monkeypatch.setattr(main, "DATA_FILE", str(data_dir / "entries.json"))
    monkeypatch.setattr(main, "PUBLISHED_FILE", str(data_dir / "published.json"))
    monkeypatch.setattr(main, "SITE_FILE", str(site_dir / "index.html"))
    monkeypatch.setattr(main, "today", lambda: TODAY)
    with TestClient(main.app) as c:
        yield c


def site_html():
    with io.open(main.SITE_FILE, encoding="utf-8") as f:
        return f.read()


def embedded_report(html):
    start = html.index('<script id="report" type="application/json">') + len('<script id="report" type="application/json">')
    return json.loads(html[start:html.index("</script>", start)])


def test_startup_writes_a_placeholder_page(client):
    report = embedded_report(site_html())
    assert report["views"]["me"]["entries"] == []


def test_add_entry_and_status_to_date(client):
    r = client.post("/api/entries", json=APPLE)
    assert r.status_code == 201
    entry_id = r.json()["id"]
    status = client.get("/api/status").json()
    assert status["to_date"][entry_id] == pytest.approx(107.40)
    assert status["summary"]["me"]["net"] == pytest.approx(107.40)
    assert status["unpublished_changes"] is True


def test_rejects_unknown_category_and_person(client):
    assert client.post("/api/entries", json=dict(APPLE, category="Nope")).status_code == 400
    assert client.post("/api/entries", json=dict(APPLE, beneficiary="Stranger")).status_code == 400


def test_rejects_end_date_on_one_time_and_before_start(client):
    one_time = dict(APPLE, frequency="one_time", end_date="2026-05-01")
    assert client.post("/api/entries", json=one_time).status_code == 400
    backwards = dict(APPLE, end_date="2025-12-01")
    assert client.post("/api/entries", json=backwards).status_code == 400


def test_rejects_non_positive_amount(client):
    assert client.post("/api/entries", json=dict(APPLE, amount=0)).status_code == 422
    assert client.post("/api/entries", json=dict(APPLE, amount=-5)).status_code == 422


def test_end_entry(client):
    entry_id = client.post("/api/entries", json=APPLE).json()["id"]
    r = client.post("/api/entries/%s/end" % entry_id, json={"end_date": "2026-03-04"})
    assert r.json()["end_date"] == "2026-03-04"
    assert client.get("/api/status").json()["to_date"][entry_id] == pytest.approx(3 * 10.74)


def test_edit_and_delete_entry(client):
    entry_id = client.post("/api/entries", json=APPLE).json()["id"]
    r = client.put("/api/entries/" + entry_id, json=dict(APPLE, amount=12))
    assert r.json()["amount"] == 12
    assert client.delete("/api/entries/" + entry_id).status_code == 204
    assert client.get("/api/data").json()["entries"] == []
    assert client.delete("/api/entries/" + entry_id).status_code == 404


def test_lists_keep_me_and_values_in_use(client):
    client.post("/api/entries", json=APPLE)
    lists = {"categories": ["Hardware"], "people": ["Me"]}
    assert client.put("/api/lists", json=lists).status_code == 400  # Subscriptions in use
    assert client.put("/api/lists", json={"categories": ["Subscriptions"], "people": ["Mom"]}).status_code == 400
    ok = client.put("/api/lists", json={"categories": ["Subscriptions", " Power tools ", "Subscriptions"], "people": ["Me", "Mom"]})
    assert ok.json() == {"categories": ["Subscriptions", "Power tools"], "people": ["Me", "Mom"]}


def test_readings_rates_settings(client):
    assert client.post("/api/readings", json={"watts": 350}).json()["date"] == "2026-10-11"
    client.post("/api/rates", json={"effective_date": "2026-01-01", "rate_per_kwh": 0.15})
    client.put("/api/settings", json={"rack_online_since": "2026-10-01"})
    me = client.get("/api/status").json()["summary"]["me"]
    assert me["spent"] == pytest.approx(10 * 350 * 24 / 1000 * 0.15)


def test_publish_snapshots_and_hides_notes(client):
    client.post("/api/entries", json=APPLE)
    status = client.post("/api/publish").json()
    assert status["unpublished_changes"] is False
    html = site_html()
    assert "SECRET-NOTE" not in html
    report = embedded_report(html)
    assert report["views"]["me"]["saved"] == pytest.approx(107.40)
    assert "notes" not in report["views"]["me"]["entries"][0]


def test_rebuild_uses_published_snapshot_not_live_edits(client):
    client.post("/api/entries", json=APPLE)
    client.post("/api/publish")
    client.post("/api/entries", json=dict(APPLE, name="Unpublished", amount=1000))
    assert client.get("/api/status").json()["unpublished_changes"] is True
    main.rebuild_public()
    assert embedded_report(site_html())["views"]["me"]["saved"] == pytest.approx(107.40)


def test_preview_shows_live_data_with_banner(client):
    client.post("/api/entries", json=APPLE)
    html = client.get("/preview").text
    assert "preview-banner" in html
    assert "SECRET-NOTE" not in html
    assert embedded_report(html)["views"]["me"]["saved"] == pytest.approx(107.40)


def test_script_breakout_is_escaped(client):
    client.post("/api/entries", json=dict(APPLE, name="</script><script>alert(1)</script>"))
    html = client.get("/preview").text
    assert "</script><script>alert(1)" not in html
    assert embedded_report(html)["views"]["me"]["entries"][0]["name"].startswith("</script>")


def test_editor_page_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "Savings Editor" in r.text
