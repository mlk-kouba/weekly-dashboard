# Weekly Engineering Dashboard — Regeneration Guide

Each week, open GitHub Copilot CLI and run through the steps below. The output is a dated
`yymmdd-weekly-dashboard.html` saved to this folder.

---

## Prompt to Use Each Week

Paste this into Copilot CLI (adjust the date and any notes):

```
Update the weekly engineering dashboard for the week of [DATE].

Boards: LEF · LEM · LRF

Labels:
- LEF active release items → **Fix Version** `August 2026 Monthly Release *` and label `AugustPrio`
- LEF look-ahead release count → label `September`
- LEF mobile tracker → label = `Mobile`

Section titles:
- LEF  → "Assessment / ReadingPowerZone / SoR"
- LEM  → "Maintenance"
- LRF  → "Literacy Integration"

Pull live data from Jira (learningaz.atlassian.net) for each board.
For each board include:
  - Stat summary (Done / In Progress / In Review / Not Started / Abandoned)
  - Progress bar with % complete and week-over-week change vs last week
  - Active work tickets (key, summary, assignee)
  - Top completed tickets this week
  - Any alerts or risks

For LEF specifically:
  - Keep the primary board focused on the configured August release (`August 2026 Monthly Release *` / `AugustPrio`)
  - Show August release status (% done, tickets in flight, unstarted risk count)
  - Show overall LEF done count across the whole board
  - Show the `September` label count as look-ahead scope
  - Track `Mobile` labelled tickets separately

For LEM:
  - Show active sprint items
  - Highlight anything completed that was flagged as at-risk last week

For LRF:
  - Show in-progress items and overall completion %
  - Note any unowned/unassigned tickets

Bottom section should include:
  - Actions Required (numbered, board-labeled)
  - Roadmap Snapshot (June → December)
  - Week-over-week comparison summary

Save as yymmdd-weekly-dashboard.html in C:/Users/mkouba/weekly-project-dashboard/
```

---

## Board Reference

| Board | Key | Jira Label (MVP) | Title in Dashboard |
|-------|-----|------------------|--------------------|
| LEF   | LEF | Fix Versions + labels (`AugustPrio`, `September`) | Assessment / ReadingPowerZone / SoR |
| LEM   | LEM | n/a (sprint-based) | Maintenance |
| LRF   | LRF | n/a | Literacy Integration |

**Jira instance:** `https://learningaz.atlassian.net`  
**Auth:** `.env` file → `JIRA_TOKEN` + `michelle.kouba@learninga-z.com`

---

## Week-Over-Week Comparison Checklist

Pull up the previous week's file from this folder and compare:

- [ ] LEF August release (`August 2026 Monthly Release *`) % done and in-flight count
- [ ] LEF September scope (`September`) count for look-ahead planning
- [ ] LEF mobile tickets: are unassigned items getting owners?
- [ ] LEM: were last week's flagged risks resolved?
- [ ] LRF: overall completion % trending up
- [ ] Any new blocked / abandoned tickets added?
- [ ] Actions from last week — which were addressed?

---

## File Naming

`yymmdd-weekly-dashboard.html`

Examples:
- `260506-weekly-dashboard.html` — May 6, 2026
- `260514-weekly-dashboard.html` — May 14, 2026
- `260521-weekly-dashboard.html` — May 21, 2026

Each generated week now saves a raw snapshot in `snapshots/yymmdd.json`. If you rerun a past week and that snapshot already exists, the dashboard is rebuilt from the saved snapshot instead of live Jira data.

For a missed Wednesday with **no** saved snapshot yet, run the workflow manually with the `dashboard_date` input set to the desired week, for example `2026-06-10`. The generator will reconstruct the board from Jira issue history and then save that reconstructed snapshot so later reruns stay consistent.

The dashboard header shows whether a page came from a **Live Jira capture** or was **Reconstructed from Jira history**.

---

## Status Badge Reference

| Badge | Meaning |
|-------|---------|
| 🔴 At Risk / Critical | Deadline at risk, immediate action needed |
| 🟡 On Track | Some items need attention but not critical |
| 🟢 Healthy | Progressing well, no blockers |

## Ticket Status Colors (in HTML)

| CSS class | Color | Jira Status |
|-----------|-------|-------------|
| `inprogress` | Blue left border | In Progress |
| `review` | Purple left border | Ready for QA, QA in Progress, Final Approval |
| `done` | Green left border | Done |
| `blocked` | Red left border | Blocked |
| `open` | Yellow left border | To Do, Open Request, Selected for Development |
| `planning` | Purple left border | Planning, Refine Ready, New |

## LEF Tracking Rules

- LEF release tracking uses the values in `dashboard_config.json`
- Release selectors are based on **Fix Versions** first, with labels kept alongside them for reference
- LEF release/mobile tracking includes subtasks because those tags are applied at that level
- A LEF item counts as **done** when its status is `Done`
- All dashboard Jira queries only include tickets with `created >= 2026-01-01`
