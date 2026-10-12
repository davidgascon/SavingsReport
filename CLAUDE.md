# Homelab Savings Report

Tracks whether my server rack is net positive or negative financially. Output is a self-contained static HTML page served on a public port, plus a LAN-only editor (separate port) where I add expenses, savings, and power readings.

## Source of truth

`SPEC.md` is the spec. Build against it, not against anything said in an old session.

- If a request conflicts with the spec, say so and propose a spec change. Don't quietly deviate.
- `SPEC.md` is an export of the Claude Doc (link at the top of the file). Spec changes are made in the doc first, then re-exported here. Don't edit `SPEC.md` as a way of making a decision.
- When a decision is made during building, give me the one-line entry for the spec's decision log.
- Items under "Open questions" are not decided. Ask before building anything that depends on one.

## Environment

Proxmox, Docker/Portainer, OPNsense, nginx Proxy Manager, Tailscale. I'm technical; skip beginner explanations.

## Working rules

- One session per task. Keep work scoped to that task.
- Deliver complete files, not partial snippets, unless I ask for a diff.
- Version deliverables (v1, v2…) and tell me what changed.
- The accrual and electricity math must have tests. The Apple TV+ example in the spec ($10.74/mo from 2026-01-04, as of 2026-10-11 = $107.40) is a required test case, as is the 350 W × 30-day = 252 kWh example.
- Totals are computed from entries at build time; never store accrued amounts.
- The public page must never expose `entries.json`, notes, or the editor.
