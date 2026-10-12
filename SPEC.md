# Homelab Savings Report — Spec v1.3

Oct 11, 2026 · David Gascon

> Source of truth: the Claude Doc "Homelab Savings Report — Spec v1"
> (https://claude.ai/code/artifact/a656adb0-b267-4b3c-b21f-027c265212fc).
> This file is an export of it. Spec changes are made there first, then re-exported here.

## Purpose and scope

A static web page that answers one question: is the server rack ahead or behind financially? It totals what the homelab has cost (hardware, power, recurring services) against what it has saved (cancelled subscriptions, replaced paid services), and shows the running net.

In scope for v1:

- A read-only static HTML page on a public port, with Me and Everyone views
- A LAN-only editor for adding, editing, and ending entries
- Entries that are expenses or savings, one-time or monthly, with a category and a beneficiary (default Me)
- Electricity cost estimated from logged average-watt readings
- Accrual math that keeps recurring entries up to date without manual edits

Out of scope for v1: live server telemetry (uptime, CPU, storage), multi-user access, currencies other than USD, and automatic bank or card imports.

## Architecture

One host serves two ports: the admin editor on a LAN-only port, and the static page on a port reachable from outside.

```
            LAN only                                   public
  ┌──────────────────────────┐              ┌──────────────────────────┐
  │ Admin editor (8086)      │   Publish    │ Static server (8085)     │
  │  - reads/writes          │ ───────────▶ │  - serves index.html     │
  │    entries.json          │  writes one  │    only                  │
  │  - Preview               │  HTML file   │                          │
  └──────────────────────────┘              └──────────────────────────┘
        ▲ firewall: allow from LAN only           ▲ firewall: forward from WAN
```

Publishing writes one self-contained HTML file into the folder the public port serves. The public port serves only that file, never entries.json or the editor. The firewall forwards the public port from outside and allows the admin port from the LAN only. Both pieces run as one Docker Compose stack on the Ubuntu server, deployed through Portainer: a Python/FastAPI editor on port 8086 (LAN only) and an nginx static server on port 8085 (public). Publish freezes a copy of the data (published.json); the page re-renders daily from that copy so totals keep accruing and unpublished edits never go public.

## Data model

Every entry is one record with a direction (expense or savings) and a frequency (one-time or monthly). Data lives in a single JSON file on the LAN host, so it is easy to back up, diff, and hand-edit.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| id | string | yes | Generated, never reused |
| name | string | yes | e.g. "Apple TV+" |
| direction | expense \| savings | yes | Savings count positive, expenses negative |
| frequency | one_time \| monthly | yes | |
| amount | number (USD) | yes | Always entered positive; direction sets the sign |
| start_date | date | yes | For one-time, the date it happened |
| end_date | date | no | Monthly only; blank means ongoing |
| category | enum | yes | Hardware, Software, Subscriptions, Services, Other; editable list |
| beneficiary | string | yes | Who it is for; defaults to "Me". Other names come from an editable people list |
| notes | string | no | Free text |

Example entries:

| Name | Direction | Frequency | Category | For | Amount | Start | End |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Apple TV+ cancelled | savings | monthly | Subscriptions | Me | $10.74 | 2026-01-04 | ongoing |
| 20-bay Unraid server | expense | one_time | Hardware | Me | (fill in) | (fill in) | |
| Streaming service a family member dropped | savings | monthly | Subscriptions | (their name) | (fill in) | (fill in) | ongoing |

Electricity is not entered as an entry; it is calculated from power readings (see Electricity).

## Calculation rules

All totals are computed at build time from the entry list; nothing accrued is stored. That way, ending or correcting an entry fixes every total automatically.

1. **One-time entries** count once, on start_date, if start_date is on or before today.
2. **Monthly entries** count once on start_date and again on the same day each month after, through the earlier of today or end_date.
   1. A start on the 29th to 31st falls on the last day of shorter months.
   2. Worked example: Apple TV+ from 2026-01-04, ongoing, as of 2026-10-11 = 10 charges (Jan 4 through Oct 4) × $10.74 = $107.40 saved.
3. **Electricity** is an expense computed from power readings (see Electricity), category Power, beneficiary Me.
4. **Net position** = total savings to date − total expenses to date. Positive means the rack is ahead.
5. **Two views** of every total:
   1. **Me:** only entries with beneficiary Me, plus all expenses and electricity.
   2. **Everyone:** all entries, so savings by other people count toward the rack.
6. **Monthly run rate** = active monthly savings − active monthly expenses − current monthly electricity cost, where active means started and not ended.
7. **Break-even estimate** applies only when net is negative and run rate is positive: months to break even = −net ÷ run rate, shown as a projected date, per view. The date is today plus the whole months, then the leftover fraction as days.

Amounts are rounded to cents only for display; sums use full precision.

## Electricity

Electricity cost is calculated from dated average-watt readings, so one reading taken today is enough to estimate the past few months.

- **Power reading:** date, average watts, optional note (e.g. "added the Unraid server")
- **Utility rate:** $/kWh with an effective date; a rate change is a new row, not an edit
- **Rack online since:** one date that sets where the electricity history starts

Each reading holds from its date until the next reading. Before the first reading, that first reading is carried back to the rack-online date. That back-fill is what turns a single reading of today's watts into an estimate for the past few months.

```
kWh  = watts × hours / 1000
cost = kWh × rate
```

Worked example: 350 W over a 30-day month = 350 × 720 ÷ 1000 = 252 kWh, then × your rate. Costs are computed per calendar month, so the chart and the monthly run rate use the same numbers. Whole days are counted up to yesterday. Rates back-fill like readings: the earliest rate is carried back to the rack-online date.

The estimate gets more accurate as readings are logged after hardware changes. Pulling watts automatically from a UPS or smart plug is a v2 candidate.

## Public page contents

The public page leads with one big number, the net position, colored green when positive and red when negative. Everything below it explains that number.

- **View toggle:** Me (default) or Everyone; every number and chart below follows it
- **Headline cards:** net position, total saved, total spent, monthly run rate, break-even date (when it applies)
- **Net over time:** a line chart of cumulative net by month since the first entry, with a zero line
- **Breakdown:** spent and saved by category, and saved by person in the Everyone view
- **Electricity:** current watts, estimated kWh and cost per month as a chart, and total cost to date
- **Entry list:** read-only table of entries with category, person, and to-date totals; notes hidden on the public page
- **Footer:** "last updated" timestamp from the build

The page is one self-contained HTML file with inline CSS and JS, and no calls back to the LAN. It must read well on a phone.

## Editor features (LAN only)

The editor is a small web app reachable only from the trusted network. It owns the JSON data file and is the only thing that writes to it.

- **Add entry:** form with name, direction, frequency, amount, start date, optional end date, category, beneficiary (pre-filled "Me"), and notes
- **End entry:** one click to set end_date on a monthly entry, such as re-subscribing to something
- **Edit and delete:** fix typos or remove mistakes
- **Log power reading:** date (defaults to today) and average watts; plus the utility rate and rack-online date as settings
- **Manage lists:** categories and people. "Me" is permanent, and a value used by an entry can't be removed
- **Preview:** shows the same view as the public page before publishing
- **Publish:** rebuilds the static HTML into the public port's folder
- **Backup:** the JSON file is included in existing backups

Natural-language entry, like "cancelling Apple TV, saving 10.74 a month since 1/4/2026, no end date," is a v2 candidate. In v1, the same sentence can go to Claude in this Project, which returns a ready-to-paste entry.

## Open questions

- [ ] Does "statistics about my server" mean financial stats only, or also live server stats like uptime and storage?
- [ ] Should the public page show dollar amounts, or only percentages and trends?
- [x] Editor stack: decided in v1.2 (Python/FastAPI editor + nginx static server, Docker Compose via Portainer)
- [x] Port numbers: decided in v1.2 (public 8085, admin 8086)
- [ ] In the Me view, should an expense bought for someone else count against me? Draft assumes yes.
- [ ] Utility rate in $/kWh, and does it vary by season or tier?
- [ ] Rack-online date for the start of electricity history
- [ ] Should savings ever stop counting automatically, e.g. after 12 months, or run until an end date is set?

## Decision log

Every change to scope, rules, or architecture gets a row here, newest first, with the spec version bumped.

| Date | Version | Decision |
| --- | --- | --- |
| 2026-10-11 | v1.3 | Publish freezes a data snapshot; page re-renders daily from it. Electricity counts whole days to yesterday; earliest rate back-fills. Break-even date = whole months + leftover days. "Me" is permanent; list values in use can't be removed |
| 2026-10-11 | v1.2 | Stack: Python/FastAPI editor + nginx static server in one Docker Compose stack on Ubuntu, deployed via Portainer. Ports: public 8085, admin 8086 (LAN only) |
| 2026-10-11 | v1.1 | Dropped the DMZ design: one host, public page on its own port, admin port LAN-only. Added categories, beneficiary (default Me) with Me/Everyone views, and electricity from watt readings |
| 2026-10-11 | v1 | Initial spec: static public page, LAN editor, JSON storage, one-time and monthly entries, accrual computed at build time |
