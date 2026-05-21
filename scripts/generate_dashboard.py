#!/usr/bin/env python3
"""
Weekly Engineering Dashboard Generator
Queries Jira for LEF, LEM, LRF boards and generates a styled HTML dashboard.

Required environment variables:
  JIRA_EMAIL      - your Atlassian account email
  JIRA_API_TOKEN  - Atlassian API token (https://id.atlassian.com/manage-profile/security/api-tokens)
  JIRA_INSTANCE   - hostname only, e.g. learningaz.atlassian.net
"""

import os
import sys
import json
import base64
import datetime
from urllib.request import urlopen, Request
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
JIRA_EMAIL    = os.environ.get("JIRA_EMAIL", "")
JIRA_TOKEN    = os.environ.get("JIRA_API_TOKEN", "")
JIRA_HOST     = os.environ.get("JIRA_INSTANCE", "learningaz.atlassian.net")
PROJECTS      = ["LEF", "LEM", "LRF"]

def active_mvp_label(today: datetime.date = None) -> str:
    """Return the current MVP label based on date. Switches to JULYMVP on July 1."""
    d = today or datetime.date.today()
    return "JULYMVP" if d >= datetime.date(d.year, 7, 1) else "JUNEMVP"

PROJECT_META = {
    "LEF": {"label": "LEF", "desc": "Assessment / ReadingPowerZone / SoR", "color": "#dc2626", "badge": "badge-red",    "board": "scrum"},
    "LEM": {"label": "LEM", "desc": "External Users / Rostering / Auth",   "color": "#f59e0b", "badge": "badge-yellow", "board": "kanban"},
    "LRF": {"label": "LRF", "desc": "Platform / Infrastructure / NG",      "color": "#22c55e", "badge": "badge-green",  "board": "scrum"},
}

STATUS_MAP = {
    "in progress":   "inprogress",
    "in development": "inprogress",
    "in review":     "review",
    "in testing":    "review",
    "code review":   "review",
    "done":          "done",
    "closed":        "done",
    "resolved":      "done",
    "blocked":       "blocked",
    "impediment":    "blocked",
    "open":          "open",
    "to do":         "open",
    "backlog":       "open",
    "selected for development": "open",
    "in planning":   "planning",
    "planning":      "planning",
}

# ---------------------------------------------------------------------------
# Jira API helpers
# ---------------------------------------------------------------------------
def _auth_header():
    creds = base64.b64encode(f"{JIRA_EMAIL}:{JIRA_TOKEN}".encode()).decode()
    return {"Authorization": f"Basic {creds}", "Content-Type": "application/json"}

def jira_get(path: str, params: dict = None) -> dict:
    url = f"https://{JIRA_HOST}/rest/api/3/{path}"
    if params:
        url += "?" + urlencode(params)
    req = Request(url, headers=_auth_header())
    try:
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except HTTPError as e:
        print(f"HTTP {e.code} calling {url}: {e.read().decode()}", file=sys.stderr)
        return {}
    except URLError as e:
        print(f"URL error calling {url}: {e.reason}", file=sys.stderr)
        return {}

def get_active_sprint_issues(project: str) -> list:
    """Return issues for a project — sprint-based for scrum, prioritized backlog for kanban.
    Filters to the active MVP label (JUNEMVP before July, JULYMVP from July onward)."""
    board = PROJECT_META[project]["board"]
    label = active_mvp_label()
    if board == "kanban":
        jql = (
            f'project = {project} AND statusCategory != Done AND labels = {label} '
            f'ORDER BY priority ASC, rank ASC'
        )
    else:
        jql = (
            f'project = {project} AND sprint in openSprints() AND labels = {label} '
            f'ORDER BY status ASC, priority DESC'
        )
    issues = []
    start  = 0
    while True:
        data = jira_get("search/jql", {
            "jql":        jql,
            "startAt":    start,
            "maxResults": 100,
            "fields":     "summary,status,assignee,priority,issuetype,labels",
        })
        if not data or "issues" not in data:
            break
        batch = data["issues"]
        issues.extend(batch)
        start += len(batch)
        if start >= data.get("total", 0):
            break
    return issues

def classify_status(raw_status: str) -> str:
    return STATUS_MAP.get(raw_status.lower().strip(), "open")

def bucket_issues(issues: list) -> dict:
    buckets = {"inprogress": [], "review": [], "done": [], "blocked": [], "open": [], "planning": []}
    for issue in issues:
        raw = issue["fields"]["status"]["name"]
        key = classify_status(raw)
        buckets[key].append(issue)
    return buckets

# ---------------------------------------------------------------------------
# HTML helpers
# ---------------------------------------------------------------------------
CSS = """
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: 'Segoe UI', Arial, sans-serif; background: #f0f2f5; color: #1a1a2e; padding: 24px; }
  header { background: linear-gradient(135deg, #1a1a2e 0%, #16213e 60%, #0f3460 100%); color: white; border-radius: 12px; padding: 24px 32px; margin-bottom: 24px; display: flex; justify-content: space-between; align-items: center; }
  header h1 { font-size: 1.6rem; font-weight: 700; letter-spacing: -0.5px; }
  header .meta { text-align: right; font-size: 0.82rem; opacity: 0.75; line-height: 1.7; }
  .grid { display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 20px; margin-bottom: 20px; }
  .card { background: white; border-radius: 12px; padding: 20px; box-shadow: 0 2px 8px rgba(0,0,0,0.07); }
  .card.full { grid-column: 1 / -1; }
  .card.two-col { grid-column: span 2; }
  .project-header { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 2px solid #f0f2f5; }
  .badge { font-size: 0.7rem; font-weight: 700; padding: 3px 10px; border-radius: 20px; letter-spacing: 0.5px; text-transform: uppercase; }
  .badge-red { background: #fee2e2; color: #dc2626; }
  .badge-yellow { background: #fef9c3; color: #b45309; }
  .badge-green { background: #dcfce7; color: #15803d; }
  .project-name { font-size: 1.1rem; font-weight: 700; }
  .project-sub { font-size: 0.78rem; color: #6b7280; margin-top: 1px; }
  .stats { display: flex; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
  .stat-box { flex: 1; min-width: 70px; background: #f8fafc; border-radius: 8px; padding: 10px 12px; text-align: center; border: 1px solid #e2e8f0; }
  .stat-box .num { font-size: 1.5rem; font-weight: 800; line-height: 1; }
  .stat-box .lbl { font-size: 0.67rem; color: #64748b; margin-top: 3px; text-transform: uppercase; letter-spacing: 0.4px; }
  .num-green { color: #16a34a; } .num-blue { color: #2563eb; } .num-orange { color: #d97706; } .num-red { color: #dc2626; } .num-gray { color: #9ca3af; }
  .progress-wrap { margin-bottom: 14px; }
  .progress-label { display: flex; justify-content: space-between; font-size: 0.75rem; color: #64748b; margin-bottom: 4px; }
  .progress-bar { height: 10px; background: #e2e8f0; border-radius: 99px; overflow: hidden; }
  .progress-fill { height: 100%; border-radius: 99px; }
  .fill-green { background: linear-gradient(90deg, #22c55e, #16a34a); }
  .fill-orange { background: linear-gradient(90deg, #fb923c, #ea580c); }
  .fill-red { background: linear-gradient(90deg, #f87171, #dc2626); }
  .section-title { font-size: 0.72rem; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 8px; }
  .ticket-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
  .ticket { display: flex; align-items: center; gap: 8px; padding: 7px 10px; background: #f8fafc; border-radius: 7px; border-left: 3px solid #e2e8f0; font-size: 0.8rem; }
  .ticket.inprogress { border-left-color: #3b82f6; } .ticket.done { border-left-color: #22c55e; }
  .ticket.blocked { border-left-color: #ef4444; } .ticket.open { border-left-color: #f59e0b; } .ticket.planning { border-left-color: #a78bfa; } .ticket.review { border-left-color: #8b5cf6; }
  .ticket-key { font-weight: 700; color: #2563eb; font-size: 0.72rem; white-space: nowrap; min-width: 75px; }
  .ticket-sum { flex: 1; color: #374151; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ticket-who { font-size: 0.7rem; color: #9ca3af; white-space: nowrap; }
  .pill { font-size: 0.65rem; padding: 2px 7px; border-radius: 99px; white-space: nowrap; font-weight: 600; }
  .pill-blue { background: #dbeafe; color: #1d4ed8; } .pill-green { background: #dcfce7; color: #15803d; }
  .pill-orange { background: #ffedd5; color: #c2410c; } .pill-red { background: #fee2e2; color: #b91c1c; }
  .pill-gray { background: #f1f5f9; color: #475569; } .pill-purple { background: #ede9fe; color: #6d28d9; }
  .alert { border-radius: 8px; padding: 10px 14px; font-size: 0.8rem; margin-bottom: 10px; display: flex; gap: 8px; align-items: flex-start; line-height: 1.5; }
  .alert-red { background: #fef2f2; border: 1px solid #fecaca; color: #7f1d1d; }
  .alert-yellow { background: #fefce8; border: 1px solid #fde68a; color: #78350f; }
  .alert-green { background: #f0fdf4; border: 1px solid #bbf7d0; color: #14532d; }
"""

def h(text: str) -> str:
    """HTML-escape a string."""
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def ticket_row(issue: dict, css_class: str) -> str:
    key      = issue["key"]
    summary  = issue["fields"]["summary"]
    assignee = issue["fields"].get("assignee") or {}
    who      = assignee.get("displayName", "Unassigned")
    jira_url = f"https://{JIRA_HOST}/browse/{key}"
    return (
        f'<div class="ticket {css_class}">'
        f'<span class="ticket-key"><a href="{jira_url}" target="_blank">{h(key)}</a></span>'
        f'<span class="ticket-sum">{h(summary)}</span>'
        f'<span class="ticket-who">{h(who)}</span>'
        f'</div>'
    )

def ticket_section(title: str, issues: list, css_class: str, limit: int = 8) -> str:
    if not issues:
        return ""
    rows = "".join(ticket_row(i, css_class) for i in issues[:limit])
    more = f'<div style="font-size:0.72rem;color:#94a3b8;margin-top:4px;">+{len(issues)-limit} more</div>' if len(issues) > limit else ""
    return f'<div class="section-title">{h(title)}</div><div class="ticket-list">{rows}{more}</div>'

def progress_bar(done: int, total: int) -> str:
    pct   = round(done / total * 100) if total else 0
    color = "fill-green" if pct >= 70 else ("fill-orange" if pct >= 40 else "fill-red")
    return (
        f'<div class="progress-wrap">'
        f'<div class="progress-label"><span>Sprint Progress</span><span>{pct}% ({done}/{total})</span></div>'
        f'<div class="progress-bar"><div class="progress-fill {color}" style="width:{pct}%"></div></div>'
        f'</div>'
    )

def project_card(project: str, issues: list) -> str:
    meta    = PROJECT_META[project]
    buckets = bucket_issues(issues)
    total   = len(issues)
    done    = len(buckets["done"])
    blocked = len(buckets["blocked"])
    in_prog = len(buckets["inprogress"])
    in_rev  = len(buckets["review"])

    stats = (
        f'<div class="stats">'
        f'<div class="stat-box"><div class="num num-gray">{total}</div><div class="lbl">Total</div></div>'
        f'<div class="stat-box"><div class="num num-blue">{in_prog}</div><div class="lbl">In Progress</div></div>'
        f'<div class="stat-box"><div class="num num-green">{done}</div><div class="lbl">Done</div></div>'
        f'<div class="stat-box"><div class="num num-red">{blocked}</div><div class="lbl">Blocked</div></div>'
        f'</div>'
    )

    body = ""
    if blocked:
        body += ticket_section("&#x1F6D1; Blocked", buckets["blocked"], "blocked")
    body += ticket_section("In Progress", buckets["inprogress"], "inprogress")
    body += ticket_section("In Review / Testing", buckets["review"], "review")
    body += ticket_section("Completed This Sprint", buckets["done"], "done", limit=5)
    body += ticket_section("Open / To Do", buckets["open"], "open", limit=5)

    return (
        f'<div class="card" style="border-top: 4px solid {meta["color"]}">'
        f'<div class="project-header">'
        f'<span class="badge {meta["badge"]}">{h(meta["label"])}</span>'
        f'<div><div class="project-name">{h(meta["label"])} <span style="font-weight:400;color:#6b7280;">&#xB7; {h(meta["desc"])}</span></div>'
        f'<div class="project-sub">{total} {"prioritized items" if meta["board"] == "kanban" else "tickets in active sprint"}</div></div>'
        f'</div>'
        f'{progress_bar(done, total)}'
        f'{stats}'
        f'{body}'
        f'</div>'
    )

def summary_card(all_issues: dict) -> str:
    rows = ""
    for proj, issues in all_issues.items():
        buckets = bucket_issues(issues)
        total   = len(issues)
        done    = len(buckets["done"])
        blocked = len(buckets["blocked"])
        in_prog = len(buckets["inprogress"])
        pct     = round(done / total * 100) if total else 0
        rows += (
            f'<tr style="border-bottom:1px solid #f0f2f5;">'
            f'<td style="padding:8px 12px;font-weight:700;color:#2563eb;">{h(proj)}</td>'
            f'<td style="padding:8px 12px;">{total}</td>'
            f'<td style="padding:8px 12px;color:#2563eb;">{in_prog}</td>'
            f'<td style="padding:8px 12px;color:#16a34a;">{done}</td>'
            f'<td style="padding:8px 12px;color:#dc2626;">{blocked}</td>'
            f'<td style="padding:8px 12px;font-weight:700;">{pct}%</td>'
            f'</tr>'
        )

    return (
        f'<div class="card full" style="border-top: 4px solid #6366f1;">'
        f'<div class="section-title">Sprint Summary</div>'
        f'<table style="width:100%;border-collapse:collapse;font-size:0.8rem;margin-top:8px;">'
        f'<thead><tr style="background:#f0f2f5;">'
        f'<th style="padding:8px 12px;text-align:left;">Board</th>'
        f'<th style="padding:8px 12px;text-align:left;">Total</th>'
        f'<th style="padding:8px 12px;text-align:left;">In Progress</th>'
        f'<th style="padding:8px 12px;text-align:left;">Done</th>'
        f'<th style="padding:8px 12px;text-align:left;">Blocked</th>'
        f'<th style="padding:8px 12px;text-align:left;">% Done</th>'
        f'</tr></thead>'
        f'<tbody>{rows}</tbody>'
        f'</table>'
        f'</div>'
    )

def render_html(all_issues: dict, date_str: str) -> str:
    cards   = "\n".join(project_card(proj, all_issues[proj]) for proj in PROJECTS)
    summary = summary_card(all_issues)
    label   = active_mvp_label(today)
    boards  = " &middot; ".join(PROJECTS)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Literacy Weekly Project Dashboard &mdash; {h(date_str)}</title>
<style>
{CSS}
</style>
</head>
<body>
<header>
  <div>
    <h1>&#x1F4DA; Literacy Weekly Project Dashboard</h1>
    <div style="font-size:0.85rem;opacity:0.85;margin-top:4px;">Boards: {boards} &nbsp;&middot;&nbsp; Tracking: <strong>{label}</strong></div>
  </div>
  <div class="meta">
    <div>Week of {h(date_str)}</div>
    <div>Auto-generated from Jira</div>
  </div>
</header>

<div class="grid">
{cards}
</div>

<div class="grid">
{summary}
</div>
</body>
</html>"""

def update_index(new_filename: str, date_str: str):
    index_path = "index.html"
    try:
        with open(index_path, "r") as f:
            content = f.read()
    except FileNotFoundError:
        content = ""

    new_entry = f'      <li><a href="{new_filename}">{h(date_str)} Weekly Dashboard</a></li>\n'

    if "<ul>" in content:
        content = content.replace("<ul>", "<ul>\n" + new_entry, 1)
    else:
        content = (
            "<!doctype html>\n<html lang='en'>\n<head><meta charset='utf-8'/>"
            "<title>Literacy Weekly Project Dashboard</title></head>\n<body>\n<h1>Literacy Weekly Project Dashboard</h1>\n"
            f"<ul>\n{new_entry}</ul>\n</body>\n</html>\n"
        )

    with open(index_path, "w") as f:
        f.write(content)
    print(f"Updated {index_path}")

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    if not JIRA_EMAIL or not JIRA_TOKEN:
        print("ERROR: JIRA_EMAIL and JIRA_API_TOKEN environment variables are required.", file=sys.stderr)
        sys.exit(1)

    today      = datetime.date.today()
    date_str   = today.strftime("%B %-d, %Y")
    file_slug  = today.strftime("%y%m%d")
    filename   = f"{file_slug}_weekly_dashboard.html"

    print(f"Fetching Jira data for {', '.join(PROJECTS)} ...")
    all_issues = {}
    for proj in PROJECTS:
        issues = get_active_sprint_issues(proj)
        print(f"  {proj}: {len(issues)} issues")
        all_issues[proj] = issues

    html = render_html(all_issues, date_str)

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated {filename}")

    update_index(filename, date_str)

if __name__ == "__main__":
    main()
