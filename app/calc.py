"""Accrual and electricity math (SPEC.md: Calculation rules, Electricity).

Pure functions over the data-file dict. Nothing accrued is ever stored: every
total is recomputed from the entry list for a given `today`.
"""
from __future__ import annotations

import calendar
from datetime import date, timedelta

ME = "Me"
POWER_CATEGORY = "Power"
VIEWS = ("me", "everyone")
AVG_DAYS_PER_MONTH = 365.25 / 12


def parse_date(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(value)


def add_months(start: date, months: int) -> date:
    """Same day-of-month `months` later; days 29-31 clamp to the month's last day."""
    y, m = divmod(start.month - 1 + months, 12)
    y += start.year
    m += 1
    return date(y, m, min(start.day, calendar.monthrange(y, m)[1]))


def month_key(d: date) -> str:
    return "%04d-%02d" % (d.year, d.month)


def next_month(d: date) -> date:
    return date(d.year + d.month // 12, d.month % 12 + 1, 1)


# --- Entries -----------------------------------------------------------------

def occurrences(entry: dict, today: date) -> list:
    """Dates an entry has counted on, through today (rules 1 and 2)."""
    start = parse_date(entry["start_date"])
    if entry["frequency"] == "one_time":
        return [start] if start <= today else []
    end = parse_date(entry.get("end_date"))
    stop = min(today, end) if end else today
    out = []
    k = 0
    while True:
        d = add_months(start, k)
        if d > stop:
            return out
        out.append(d)
        k += 1


def signed_amount(entry: dict) -> float:
    """Savings positive, expenses negative."""
    amount = float(entry["amount"])
    return amount if entry["direction"] == "savings" else -amount


def in_view(entry: dict, view: str) -> bool:
    """Me: beneficiary Me plus every expense. Everyone: all entries (rule 5)."""
    if view == "everyone":
        return True
    return entry["direction"] == "expense" or entry.get("beneficiary", ME) == ME


def is_active_monthly(entry: dict, today: date) -> bool:
    if entry["frequency"] != "monthly":
        return False
    start = parse_date(entry["start_date"])
    end = parse_date(entry.get("end_date"))
    return start <= today and (end is None or end >= today)


# --- Electricity -------------------------------------------------------------

def _step_lookup(rows: list, date_key: str, value_key: str):
    """Return f(d) -> value of the latest row dated on/before d.

    Before the first row, the first row's value is carried back (back-fill).
    """
    ordered = sorted(rows, key=lambda r: r[date_key])
    dates = [parse_date(r[date_key]) for r in ordered]
    values = [float(r[value_key]) for r in ordered]

    def lookup(d: date) -> float:
        value = values[0]
        for row_date, row_value in zip(dates, values):
            if row_date > d:
                break
            value = row_value
        return value

    return lookup


def electricity(data: dict, today: date) -> dict:
    """Daily kWh and cost from watt readings and $/kWh rates, grouped by calendar month.

    Counts whole days from the rack-online date (or the first reading if unset)
    up to, not including, today. Both readings and rates back-fill to the start.
    """
    readings = data.get("power_readings") or []
    rates = data.get("rates") or []
    result = {
        "available": bool(readings and rates),
        "months": [],
        "total_kwh": 0.0,
        "total_cost": 0.0,
        "current_watts": None,
        "current_rate": None,
        "current_month_cost": 0.0,
        "start_date": None,
    }
    if not result["available"]:
        return result

    watts_on = _step_lookup(readings, "date", "watts")
    rate_on = _step_lookup(rates, "effective_date", "rate_per_kwh")
    first_reading = min(parse_date(r["date"]) for r in readings)
    start = parse_date((data.get("settings") or {}).get("rack_online_since")) or first_reading

    months = {}
    d = start
    while d < today:
        kwh = watts_on(d) * 24 / 1000
        bucket = months.setdefault(month_key(d), {"month": month_key(d), "kwh": 0.0, "cost": 0.0})
        bucket["kwh"] += kwh
        bucket["cost"] += kwh * rate_on(d)
        d += timedelta(days=1)

    current_watts = watts_on(today)
    current_rate = rate_on(today)
    days_this_month = calendar.monthrange(today.year, today.month)[1]
    result.update(
        months=[months[k] for k in sorted(months)],
        total_kwh=sum(m["kwh"] for m in months.values()),
        total_cost=sum(m["cost"] for m in months.values()),
        current_watts=current_watts,
        current_rate=current_rate,
        current_month_cost=current_watts * 24 * days_this_month / 1000 * current_rate,
        start_date=start.isoformat(),
    )
    return result


# --- Summary -----------------------------------------------------------------

def _month_range(first: date, last: date) -> list:
    out = []
    d = date(first.year, first.month, 1)
    while d <= last:
        out.append(month_key(d))
        d = next_month(d)
    return out


def summarize(data: dict, today: date, view: str = "me", elec: dict = None) -> dict:
    """Every total the public page shows, for one view."""
    if view not in VIEWS:
        raise ValueError("unknown view %r" % view)
    if elec is None:
        elec = electricity(data, today)

    saved = spent = run_rate = 0.0
    by_month = {}
    by_category = {}
    by_person = {}
    rows = []
    first_date = None

    for entry in data.get("entries") or []:
        if not in_view(entry, view):
            continue
        dates = occurrences(entry, today)
        amount = signed_amount(entry)
        to_date = amount * len(dates)
        category = entry.get("category") or "Other"
        cat = by_category.setdefault(category, {"saved": 0.0, "spent": 0.0})
        if amount >= 0:
            saved += to_date
            cat["saved"] += to_date
            person = entry.get("beneficiary") or ME
            by_person[person] = by_person.get(person, 0.0) + to_date
        else:
            spent += -to_date
            cat["spent"] += -to_date
        for d in dates:
            by_month[month_key(d)] = by_month.get(month_key(d), 0.0) + amount
            if first_date is None or d < first_date:
                first_date = d
        if is_active_monthly(entry, today):
            run_rate += amount
        rows.append({
            "id": entry.get("id"),
            "name": entry["name"],
            "direction": entry["direction"],
            "frequency": entry["frequency"],
            "category": category,
            "beneficiary": entry.get("beneficiary") or ME,
            "amount": float(entry["amount"]),
            "start_date": entry["start_date"],
            "end_date": entry.get("end_date") or None,
            "count": len(dates),
            "to_date": to_date,
            "active": is_active_monthly(entry, today),
        })

    # Electricity is an expense for Me, so it is in both views (rule 3).
    if elec["available"]:
        spent += elec["total_cost"]
        if elec["total_cost"]:
            cat = by_category.setdefault(POWER_CATEGORY, {"saved": 0.0, "spent": 0.0})
            cat["spent"] += elec["total_cost"]
        for m in elec["months"]:
            by_month[m["month"]] = by_month.get(m["month"], 0.0) - m["cost"]
        run_rate -= elec["current_month_cost"]
        elec_start = parse_date(elec["start_date"])
        if first_date is None or elec_start < first_date:
            first_date = elec_start

    net = saved - spent

    timeline = []
    if first_date is not None:
        cumulative = 0.0
        for key in _month_range(first_date, today):
            change = by_month.get(key, 0.0)
            cumulative += change
            timeline.append({"month": key, "change": change, "net": cumulative})

    break_even = None
    if net < 0 and run_rate > 0:
        months = -net / run_rate
        whole = int(months)
        projected = add_months(today, whole) + timedelta(days=round((months - whole) * AVG_DAYS_PER_MONTH))
        break_even = {"months": months, "date": projected.isoformat()}

    rows.sort(key=lambda r: (r["start_date"], r["name"]), reverse=True)
    return {
        "view": view,
        "net": net,
        "saved": saved,
        "spent": spent,
        "run_rate": run_rate,
        "break_even": break_even,
        "timeline": timeline,
        "by_category": [
            {"category": k, "saved": v["saved"], "spent": v["spent"]}
            for k, v in sorted(by_category.items(), key=lambda kv: -(kv[1]["saved"] + kv[1]["spent"]))
        ],
        "by_person": [
            {"person": k, "saved": v}
            for k, v in sorted(by_person.items(), key=lambda kv: -kv[1])
        ],
        "entries": rows,
    }


def report(data: dict, today: date) -> dict:
    """Both views plus electricity: the payload embedded in the public page."""
    elec = electricity(data, today)
    return {
        "today": today.isoformat(),
        "views": {view: summarize(data, today, view, elec) for view in VIEWS},
        "electricity": elec,
    }
