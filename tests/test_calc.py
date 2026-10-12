from datetime import date

import pytest

from app import calc

TODAY = date(2026, 10, 11)


def entry(**kw):
    base = {
        "id": "x",
        "name": "Thing",
        "direction": "savings",
        "frequency": "monthly",
        "amount": 10,
        "start_date": "2026-01-01",
        "end_date": None,
        "category": "Subscriptions",
        "beneficiary": "Me",
    }
    base.update(kw)
    return base


def data(entries=(), readings=(), rates=(), rack_online=None):
    return {
        "settings": {"rack_online_since": rack_online},
        "entries": list(entries),
        "power_readings": list(readings),
        "rates": list(rates),
    }


# --- Spec worked examples ----------------------------------------------------

def test_apple_tv_example():
    apple = entry(name="Apple TV+", amount=10.74, start_date="2026-01-04")
    dates = calc.occurrences(apple, TODAY)
    assert len(dates) == 10
    assert dates[0] == date(2026, 1, 4)
    assert dates[-1] == date(2026, 10, 4)
    s = calc.summarize(data([apple]), TODAY)
    assert s["saved"] == pytest.approx(107.40)
    assert s["net"] == pytest.approx(107.40)


def test_electricity_350w_30_day_month_is_252_kwh():
    d = data(
        readings=[{"id": "r", "date": "2026-09-01", "watts": 350}],
        rates=[{"id": "p", "effective_date": "2026-01-01", "rate_per_kwh": 0.15}],
    )
    e = calc.electricity(d, date(2026, 10, 1))
    assert [m["month"] for m in e["months"]] == ["2026-09"]
    assert e["months"][0]["kwh"] == pytest.approx(252)
    assert e["months"][0]["cost"] == pytest.approx(252 * 0.15)


# --- Accrual -----------------------------------------------------------------

def test_one_time_counts_once_only_if_not_in_future():
    past = entry(frequency="one_time", start_date="2026-03-01")
    future = entry(frequency="one_time", start_date="2026-12-01")
    assert calc.occurrences(past, TODAY) == [date(2026, 3, 1)]
    assert calc.occurrences(future, TODAY) == []


def test_monthly_counts_on_start_day_itself():
    e = entry(start_date="2026-10-11")
    assert calc.occurrences(e, TODAY) == [TODAY]


def test_monthly_future_start_counts_nothing():
    assert calc.occurrences(entry(start_date="2026-11-01"), TODAY) == []


def test_monthly_stops_at_end_date_inclusive():
    e = entry(start_date="2026-01-15", end_date="2026-04-15")
    assert len(calc.occurrences(e, TODAY)) == 4
    e = entry(start_date="2026-01-15", end_date="2026-04-14")
    assert len(calc.occurrences(e, TODAY)) == 3


def test_month_end_start_clamps_without_drifting():
    e = entry(start_date="2026-01-31")
    dates = calc.occurrences(e, date(2026, 5, 31))
    assert dates == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
        date(2026, 5, 31),
    ]


def test_leap_year_clamp():
    assert calc.add_months(date(2028, 1, 30), 1) == date(2028, 2, 29)


def test_ending_entry_changes_totals_without_stored_state():
    e = entry(amount=5, start_date="2026-01-01")
    assert calc.summarize(data([e]), TODAY)["saved"] == pytest.approx(50)
    e["end_date"] = "2026-03-01"
    assert calc.summarize(data([e]), TODAY)["saved"] == pytest.approx(15)


# --- Views ---------------------------------------------------------------------

def test_me_view_excludes_others_savings_but_keeps_all_expenses():
    mine = entry(amount=10, start_date="2026-10-01")
    theirs = entry(amount=20, start_date="2026-10-01", beneficiary="Mom")
    gift = entry(direction="expense", frequency="one_time", amount=100,
                 start_date="2026-10-01", beneficiary="Mom", category="Hardware")
    d = data([mine, theirs, gift])
    me = calc.summarize(d, TODAY, "me")
    everyone = calc.summarize(d, TODAY, "everyone")
    assert me["saved"] == pytest.approx(10)
    assert me["spent"] == pytest.approx(100)
    assert everyone["saved"] == pytest.approx(30)
    assert everyone["spent"] == pytest.approx(100)
    assert {p["person"] for p in everyone["by_person"]} == {"Me", "Mom"}


def test_unknown_view_rejected():
    with pytest.raises(ValueError):
        calc.summarize(data(), TODAY, "nobody")


# --- Run rate and break-even -------------------------------------------------

def test_run_rate_counts_only_active_monthly_entries():
    d = data([
        entry(amount=20, start_date="2026-01-01"),
        entry(amount=50, start_date="2026-01-01", end_date="2026-05-01"),  # ended
        entry(amount=99, start_date="2026-12-01"),                         # not started
        entry(direction="expense", amount=5, start_date="2026-02-01"),
        entry(frequency="one_time", amount=500, start_date="2026-02-01"),
    ])
    assert calc.summarize(d, TODAY)["run_rate"] == pytest.approx(15)


def test_break_even_when_behind_with_positive_run_rate():
    d = data([
        entry(direction="expense", frequency="one_time", amount=1000,
              start_date="2026-10-01", category="Hardware"),
        entry(amount=100, start_date="2026-10-01"),
    ])
    s = calc.summarize(d, TODAY)
    assert s["net"] == pytest.approx(-900)
    assert s["break_even"]["months"] == pytest.approx(9)
    assert s["break_even"]["date"] == "2027-07-11"


def test_no_break_even_when_ahead_or_run_rate_not_positive():
    ahead = data([entry(amount=100, start_date="2026-10-01")])
    assert calc.summarize(ahead, TODAY)["break_even"] is None
    stuck = data([entry(direction="expense", frequency="one_time", amount=100,
                        start_date="2026-10-01")])
    assert calc.summarize(stuck, TODAY)["break_even"] is None


# --- Electricity ---------------------------------------------------------------

RATE = [{"id": "p", "effective_date": "2026-01-01", "rate_per_kwh": 0.10}]


def test_single_reading_backfills_to_rack_online_date():
    d = data(readings=[{"id": "r", "date": "2026-10-01", "watts": 1000}],
             rates=RATE, rack_online="2026-09-01")
    e = calc.electricity(d, TODAY)
    assert [m["month"] for m in e["months"]] == ["2026-09", "2026-10"]
    assert e["months"][0]["kwh"] == pytest.approx(30 * 24)
    assert e["months"][1]["kwh"] == pytest.approx(10 * 24)  # Oct 1-10, today excluded
    assert e["total_cost"] == pytest.approx(40 * 24 * 0.10)


def test_reading_holds_until_next_reading():
    d = data(readings=[{"id": "a", "date": "2026-09-01", "watts": 1000},
                       {"id": "b", "date": "2026-09-11", "watts": 2000}],
             rates=RATE)
    e = calc.electricity(d, date(2026, 9, 21))
    assert e["total_kwh"] == pytest.approx(10 * 24 + 10 * 48)
    assert e["current_watts"] == 2000


def test_rate_change_is_a_new_row():
    d = data(readings=[{"id": "a", "date": "2026-09-01", "watts": 1000}],
             rates=[{"id": "p1", "effective_date": "2026-01-01", "rate_per_kwh": 0.10},
                    {"id": "p2", "effective_date": "2026-09-11", "rate_per_kwh": 0.20}])
    e = calc.electricity(d, date(2026, 9, 21))
    assert e["total_cost"] == pytest.approx(10 * 24 * 0.10 + 10 * 24 * 0.20)
    assert e["current_rate"] == pytest.approx(0.20)


def test_current_month_cost_uses_days_in_current_month():
    d = data(readings=[{"id": "a", "date": "2026-10-01", "watts": 1000}], rates=RATE)
    e = calc.electricity(d, TODAY)
    assert e["current_month_cost"] == pytest.approx(31 * 24 * 0.10)


def test_electricity_needs_both_readings_and_a_rate():
    assert not calc.electricity(data(readings=[{"id": "a", "date": "2026-10-01", "watts": 1}]), TODAY)["available"]
    assert not calc.electricity(data(rates=RATE), TODAY)["available"]


def test_electricity_counts_against_both_views():
    d = data(readings=[{"id": "a", "date": "2026-10-01", "watts": 1000}],
             rates=RATE, rack_online="2026-10-01")
    for view in calc.VIEWS:
        s = calc.summarize(d, TODAY, view)
        assert s["spent"] == pytest.approx(10 * 24 * 0.10)
        assert s["run_rate"] == pytest.approx(-31 * 24 * 0.10)
        assert s["by_category"][0]["category"] == "Power"


# --- Timeline ------------------------------------------------------------------

def test_timeline_is_cumulative_by_month_with_gaps_filled():
    d = data([
        entry(direction="expense", frequency="one_time", amount=300,
              start_date="2026-07-20", category="Hardware"),
        entry(amount=100, start_date="2026-09-05"),
    ])
    t = calc.summarize(d, TODAY)["timeline"]
    assert [p["month"] for p in t] == ["2026-07", "2026-08", "2026-09", "2026-10"]
    assert [p["net"] for p in t] == pytest.approx([-300, -300, -200, -100])
