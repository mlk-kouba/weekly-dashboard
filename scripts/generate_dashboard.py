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
import re
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
DATE_OVERRIDE = os.environ.get("DASHBOARD_DATE", "").strip()
CONFIG_FILE = "dashboard_config.json"


class JiraQueryError(RuntimeError):
    """Raised when Jira cannot be queried reliably enough to build the dashboard."""


def load_dashboard_config() -> dict:
    try:
        with open(CONFIG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError as exc:
        raise JiraQueryError(f"Missing required config file: {CONFIG_FILE}") from exc
    except json.JSONDecodeError as exc:
        raise JiraQueryError(f"Invalid JSON in {CONFIG_FILE}: {exc}") from exc


def parse_dashboard_date(raw: str = "") -> datetime.date:
    if not raw:
        return datetime.date.today()
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(
            f"Invalid DASHBOARD_DATE '{raw}'. Expected YYYY-MM-DD, for example 2026-06-10."
        ) from exc


def release_label_display(label: str) -> str:
    release = RELEASES_BY_LABEL.get(label, {})
    return release.get("display", label)


DASHBOARD_CONFIG = load_dashboard_config()
LEF_RULES = DASHBOARD_CONFIG["lef"]
LEF_ACTIVE_RELEASE = LEF_RULES["active_release"]
LEF_LOOKAHEAD_RELEASES = LEF_RULES.get("lookahead_releases", [])
LEF_MOBILE_LABEL = LEF_RULES.get("mobile_label", "Mobile")
LEF_INCLUDE_SUBTASKS = LEF_RULES.get("include_subtasks", True)
RELEASES_BY_LABEL = {
    release["label"]: release
    for release in [LEF_ACTIVE_RELEASE, *LEF_LOOKAHEAD_RELEASES]
}

def _first_wednesday(year: int, month: int) -> datetime.date:
    """Return the first Wednesday of the given month."""
    d = datetime.date(year, month, 1)
    offset = (2 - d.weekday()) % 7   # Wednesday = weekday() == 2
    return d + datetime.timedelta(days=offset)

def _release_schedule(today: datetime.date) -> list:
    """Return list of (release_date, freeze_date, label) for the next 12 months."""
    schedule = []
    for delta in range(12):
        total_months = today.month - 1 + delta
        year  = today.year + total_months // 12
        month = total_months % 12 + 1
        release = _first_wednesday(year, month)
        # freeze is always 7 calendar days before release
        freeze  = release - datetime.timedelta(days=7)
        label   = release.strftime("%B").upper() + "MVP"
        schedule.append((release, freeze, label))
    return schedule

def next_release_info(today: datetime.date = None) -> dict:
    """Return a dict describing the next upcoming release (the one we're building toward)."""
    d = today or datetime.date.today()
    for release, freeze, label in _release_schedule(d):
        if release >= d:
            dtf = (freeze - d).days
            return {
                "release": release,
                "freeze":  freeze,
                "label":   label,
                "display": release.strftime("%B") + " MVP",
                "release_str": release.strftime("%B %-d, %Y"),
                "freeze_str":  freeze.strftime("%B %-d, %Y"),
                "days_to_freeze": dtf,
            }
    return {}

def active_mvp_label(today: datetime.date = None) -> str:
    """Return the active LEF release label."""
    return LEF_ACTIVE_RELEASE["label"]

PROJECT_META = {
    "LEF": {
        "label": "LEF", "desc": "Assessment / ReadingPowerZone / SoR",
        "color": "#dc2626", "badge": "badge-critical",
        "mvp_label": True,
        "sub": "{total} tickets · <span style=\"color:#dc2626;font-weight:600;\">{mvp_name} deadline</span>",
        "done_label": "Done", "open_label": "Not Started",
        "completed_label": "&#x2705; Completed This Sprint",
    },
    "LEM": {
        "label": "LEM", "desc": "Maintenance",
        "color": "#f59e0b", "badge": "badge-yellow",
        "mvp_label": False,
        "sub": "{backlog} in backlog &middot; Kanban &middot; No hard deadline",
        "done_label": "Done (Month)", "open_label": "Planned/Open",
        "completed_label": "&#x2705; Completed This Week",
    },
    "LRF": {
        "label": "LRF", "desc": "Literacy Integration",
        "color": "#22c55e", "badge": "badge-green",
        "mvp_label": False,
        "sub": "Foundation / infra work &middot; No hard deadline",
        "done_label": "Done (Month)", "open_label": "New/Sel",
        "completed_label": "Recently Completed &#x2705;",
    },
}

STATUS_MAP = {
    # In Progress
    "in progress":            "inprogress",
    "in development":         "inprogress",
    "active":                 "inprogress",
    "working":                "inprogress",
    # In Review
    "in review":              "review",
    "in testing":             "review",
    "code review":            "review",
    "qa":                     "review",
    "testing":                "review",
    "peer review":            "review",
    "verify ready":           "review",
    "verifying":              "review",
    "final review":           "review",
    "in final review":        "review",
    # Done
    "done":                   "done",
    "closed":                 "done",
    "resolved":               "done",
    "complete":               "done",
    "completed":              "done",
    # Not Started / Open
    "open":                   "open",
    "open request":           "open",
    "to do":                  "open",
    "backlog":                "open",
    "selected for development": "open",
    "in planning":            "open",
    "planning":               "open",
    "new":                    "open",
    "ready":                  "open",
    # Abandoned
    "abandoned":              "abandoned",
    "cancelled":              "abandoned",
    "canceled":               "abandoned",
    "won't fix":              "abandoned",
    "wont fix":               "abandoned",
    "duplicate":              "abandoned",
    "invalid":                "abandoned",
    "blocked":                "abandoned",
    "impediment":             "abandoned",
}
for bucket, statuses in LEF_RULES.get("status_groups", {}).items():
    for status in statuses:
        STATUS_MAP[status.lower().strip()] = bucket

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
            data = json.loads(resp.read().decode())
            if isinstance(data, dict) and data.get("errorMessages"):
                raise JiraQueryError(f"Jira query failed for {url}: {'; '.join(data['errorMessages'])}")
            return data
    except HTTPError as e:
        raise JiraQueryError(f"HTTP {e.code} calling {url}: {e.read().decode()}") from e
    except URLError as e:
        raise JiraQueryError(f"URL error calling {url}: {e.reason}") from e


def jira_total(jql: str) -> int:
    data = jira_get("search/jql", {
        "jql": jql,
        "startAt": 0,
        "maxResults": 1,
        "fields": "summary",
    })
    return data.get("total", 0)


def jira_search_issues(jql: str, fields: str = "summary,status,assignee,priority,issuetype,labels") -> list:
    issues = []
    start = 0
    while True:
        data = jira_get("search/jql", {
            "jql": jql,
            "startAt": start,
            "maxResults": 100,
            "fields": fields,
        })
        batch = data.get("issues", [])
        issues.extend(batch)
        start += len(batch)
        if start >= data.get("total", 0) or not batch:
            break
    return issues


def validate_jira_access():
    me = jira_get("myself")
    if not me.get("accountId"):
        raise JiraQueryError(
            "Jira authentication succeeded without an account identity. "
            "Verify the JIRA_EMAIL and JIRA_API_TOKEN secrets."
        )


def jql_quote(value: str) -> str:
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def lef_issue_type_clause() -> str:
    return "" if LEF_INCLUDE_SUBTASKS else ' AND issuetype != "Sub-task"'


def lef_release_clause(release: dict) -> str:
    clauses = []
    fix_version = release.get("fix_version")
    label = release.get("label")
    if fix_version:
        clauses.append(f"fixVersion = {jql_quote(fix_version)}")
    if label:
        clauses.append(f"labels = {jql_quote(label)}")
    if not clauses:
        raise JiraQueryError("LEF release config must define at least one of fix_version or label.")
    return "(" + " OR ".join(clauses) + ")" + lef_issue_type_clause()


def get_active_sprint_issues(project: str, today: datetime.date = None) -> list:
    """Return issues for a project.
    LEF: all JUNEMVP/JULYMVP tickets across ALL sprints (Done = all MVP done tickets).
    LEM and LRF: all not-done tickets + done tickets updated this month (Done = done this month)."""
    d     = today or datetime.date.today()
    meta  = PROJECT_META[project]
    label = active_mvp_label(d)
    if meta["mvp_label"]:
        # LEF: use the configured release selectors as the source of truth.
        jql = (
            f"project = {project} AND {lef_release_clause(LEF_ACTIVE_RELEASE)} "
            f'ORDER BY status ASC, priority DESC'
        )
    else:
        # LEM/LRF: active tickets updated this year + done tickets updated in the target month.
        year_start = datetime.date(d.year, 1, 1).strftime("%Y-%m-%d")
        month_start = d.replace(day=1).strftime("%Y-%m-%d")
        day_after = (d + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        jql = (
            f'project = {project} AND issuetype != Sub-task AND ('
            f'(statusCategory != Done AND updatedDate >= "{year_start}" AND updatedDate < "{day_after}") OR '
            f'(statusCategory = Done AND updatedDate >= "{month_start}" AND updatedDate < "{day_after}")'
            f') ORDER BY status ASC, updated DESC'
        )
    issues = jira_search_issues(jql)

    print(f"  {project}: {len(issues)} issues")
    if issues:
        statuses = sorted(set(i["fields"]["status"]["name"] for i in issues))
        print(f"  {project} statuses found: {', '.join(statuses)}")
    return issues

def fetch_lef_release_counts() -> dict:
    counts = {}
    for release in [LEF_ACTIVE_RELEASE, *LEF_LOOKAHEAD_RELEASES]:
        label = release["label"]
        total = jira_total(f"project = LEF AND {lef_release_clause(release)}")
        counts[label] = total
        print(f"  LEF {label} total: {total}")
    return counts


def fetch_lef_mobile_issues() -> list:
    issues = jira_search_issues(
        f"project = LEF AND labels = {jql_quote(LEF_MOBILE_LABEL)}{lef_issue_type_clause()} ORDER BY status ASC, priority DESC"
    )
    print(f"  LEF Mobile total: {len(issues)} issues")
    return issues


def validate_issue_counts(all_issues: dict, prev_stats: dict):
    suspicious = []
    for proj in PROJECTS:
        prev_total = (prev_stats.get(proj) or {}).get("total", 0)
        curr_total = len(all_issues.get(proj, []))
        if prev_total > 0 and curr_total == 0:
            suspicious.append(proj)
    if suspicious:
        raise JiraQueryError(
            "Refusing to publish a blank board snapshot. "
            f"The following projects dropped from non-zero last week to zero now: {', '.join(suspicious)}. "
            "Verify the JIRA_EMAIL and JIRA_API_TOKEN secrets and confirm that the service account can browse those projects."
        )

def classify_status(raw_status: str, status_category_key: str = "") -> str:
    """STATUS_MAP always wins for known statuses; fall back to Jira statusCategory for unknowns."""
    mapped = STATUS_MAP.get(raw_status.lower().strip())
    if mapped:
        return mapped
    # Unknown status — use Jira's statusCategory as fallback
    cat = status_category_key.lower()
    if cat == "done":
        return "done"
    if cat == "indeterminate":   # Jira's "In Progress" category
        return "inprogress"
    return "open"                # Jira's "To Do" / unknown

def bucket_issues(issues: list) -> dict:
    buckets = {"inprogress": [], "review": [], "done": [], "abandoned": [], "open": []}
    for issue in issues:
        status_field = issue["fields"]["status"]
        raw          = status_field["name"]
        cat_key      = status_field.get("statusCategory", {}).get("key", "")
        key          = classify_status(raw, cat_key)
        if key not in buckets:
            key = "open"
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
  .project-header { display: flex; align-items: flex-start; gap: 10px; margin-bottom: 16px; padding-bottom: 12px; border-bottom: 2px solid #f0f2f5; }
  .badge { font-size: 0.7rem; font-weight: 700; padding: 3px 10px; border-radius: 20px; letter-spacing: 0.5px; white-space: nowrap; }
  .badge-critical { background: #fee2e2; color: #dc2626; }
  .badge-yellow { background: #fef9c3; color: #b45309; }
  .badge-green { background: #dcfce7; color: #15803d; }
  .badge-blue { background: #dbeafe; color: #1d4ed8; }
  .project-name { font-size: 1.1rem; font-weight: 700; }
  .project-sub { font-size: 0.78rem; color: #6b7280; margin-top: 1px; }
  .stats { display: flex; gap: 8px; margin-bottom: 16px; flex-wrap: wrap; }
  .stat-box { flex: 1; min-width: 60px; background: #f8fafc; border-radius: 8px; padding: 10px 8px; text-align: center; border: 1px solid #e2e8f0; }
  .stat-box .num { font-size: 1.5rem; font-weight: 800; line-height: 1; }
  .stat-box .lbl { font-size: 0.65rem; color: #64748b; margin-top: 3px; text-transform: uppercase; letter-spacing: 0.4px; }
  .num-green { color: #16a34a; } .num-blue { color: #2563eb; } .num-orange { color: #d97706; } .num-red { color: #dc2626; } .num-gray { color: #9ca3af; }
  .progress-wrap { margin-bottom: 14px; }
  .progress-label { display: flex; justify-content: space-between; align-items: center; font-size: 0.75rem; color: #64748b; margin-bottom: 4px; }
  .progress-bar { height: 10px; background: #e2e8f0; border-radius: 99px; overflow: hidden; }
  .progress-fill { height: 100%; border-radius: 99px; }
  .fill-green { background: linear-gradient(90deg, #22c55e, #16a34a); }
  .fill-orange { background: linear-gradient(90deg, #fb923c, #ea580c); }
  .fill-red { background: linear-gradient(90deg, #f87171, #dc2626); }
  .divider { border: none; border-top: 1px solid #f0f2f5; margin: 12px 0; }
  .section-title { font-size: 0.72rem; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: 0.8px; margin-bottom: 8px; }
  .ticket-list { display: flex; flex-direction: column; gap: 6px; margin-bottom: 14px; }
  .ticket { display: flex; align-items: center; gap: 8px; padding: 7px 10px; background: #f8fafc; border-radius: 7px; border-left: 3px solid #e2e8f0; font-size: 0.8rem; }
  .ticket.inprogress { border-left-color: #3b82f6; }
  .ticket.done { border-left-color: #22c55e; }
  .ticket.open { border-left-color: #f59e0b; }
  .ticket.review { border-left-color: #8b5cf6; }
  .ticket.abandoned { border-left-color: #9ca3af; }
  .ticket-key { font-weight: 700; color: #2563eb; font-size: 0.72rem; white-space: nowrap; min-width: 75px; }
  .ticket-key a { color: inherit; text-decoration: none; }
  .ticket-key a:hover { text-decoration: underline; }
  .ticket-sum { flex: 1; color: #374151; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .ticket-who { font-size: 0.7rem; color: #9ca3af; white-space: nowrap; }
  .pill { font-size: 0.65rem; padding: 2px 7px; border-radius: 99px; white-space: nowrap; font-weight: 600; }
  .pill-green { background: #dcfce7; color: #15803d; }
  .pill-orange { background: #ffedd5; color: #c2410c; }
  .pill-purple { background: #ede9fe; color: #6d28d9; }
  .alert { border-radius: 8px; padding: 10px 14px; font-size: 0.8rem; margin-bottom: 10px; display: flex; gap: 8px; align-items: flex-start; line-height: 1.5; }
  .alert-icon { font-size: 1rem; flex-shrink: 0; }
  .alert-red { background: #fef2f2; border: 1px solid #fecaca; color: #7f1d1d; }
  .alert-yellow { background: #fefce8; border: 1px solid #fde68a; color: #78350f; }
  .action-list { list-style: none; display: flex; flex-direction: column; gap: 10px; margin-top: 8px; }
  .action-list li { display: flex; gap: 10px; align-items: flex-start; font-size: 0.82rem; line-height: 1.5; }
  .action-num { background: #6366f1; color: white; font-weight: 800; font-size: 0.72rem; border-radius: 99px; width: 20px; height: 20px; display: flex; align-items: center; justify-content: center; flex-shrink: 0; margin-top: 1px; }
  .action-text { color: #374151; }
  code { background: #f1f5f9; padding: 1px 5px; border-radius: 4px; font-size: 0.8rem; color: #7c3aed; }
  .pill-gray   { background: #f1f5f9; color: #475569; }
  .pill-purple { background: #ede9fe; color: #6d28d9; }
  .pill-red    { background: #fee2e2; color: #b91c1c; }
  .pill-blue   { background: #dbeafe; color: #1d4ed8; }
  .wow-table th { padding: 8px 12px; text-align: left; font-size: 0.68rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.5px; }
  .wow-table td { padding: 8px 12px; color: #374151; font-size: 0.8rem; }
  .wow-table tr:nth-child(even) { background: #fafafa; }
  .wow-table tr { border-bottom: 1px solid #f0f2f5; }
  .change-pill { font-weight: 700; padding: 3px 8px; border-radius: 99px; font-size: 0.75rem; }
  .change-up   { background: #dcfce7; color: #15803d; }
  .change-down { background: #fee2e2; color: #b91c1c; }
  .change-new  { background: #ede9fe; color: #6d28d9; }
  .change-flat { background: #f1f5f9; color: #64748b; }
"""  # NOTE: RELEASE_BANNER_CSS is appended in render_html via CSS + RELEASE_BANNER_CSS

RELEASE_BANNER_CSS = """
  .release-banner { background: white; border-radius: 10px; padding: 12px 22px; margin-bottom: 20px;
    display: flex; align-items: center; gap: 24px; box-shadow: 0 2px 8px rgba(0,0,0,.07);
    border-left: 5px solid #f59e0b; flex-wrap: wrap; }
  .rb-block { display: flex; flex-direction: column; }
  .rb-label { font-size: 0.68rem; font-weight: 700; color: #94a3b8; text-transform: uppercase; letter-spacing: .06em; }
  .rb-val   { font-size: 1.05rem; font-weight: 800; color: #1a1a2e; line-height: 1.3; }
  .rb-sep   { height: 36px; width: 1px; background: #e2e8f0; flex-shrink: 0; }
  .freeze-chip { font-size: 0.82rem; font-weight: 700; padding: 5px 14px; border-radius: 99px; }
  .fc-urgent { background: #fee2e2; color: #991b1b; }
  .fc-warn   { background: #fef9c3; color: #92400e; }
  .fc-ok     { background: #dcfce7; color: #15803d; }
"""

def release_banner_html(info: dict) -> str:
    """Render the top-of-page next-release banner."""
    if not info:
        return ""
    dtf = info["days_to_freeze"]
    if dtf < 0:
        chip_cls, chip_txt = "fc-urgent", "Freeze passed"
    elif dtf == 0:
        chip_cls, chip_txt = "fc-urgent", "Freeze TODAY"
    elif dtf <= 5:
        chip_cls, chip_txt = "fc-urgent", f"{dtf} day{'s' if dtf != 1 else ''} to freeze &#x1F6A8;"
    elif dtf <= 14:
        chip_cls, chip_txt = "fc-warn", f"{dtf} days to freeze"
    else:
        chip_cls, chip_txt = "fc-ok", f"{dtf} days to freeze"
    return (
        f'<div class="release-banner">'
        f'<div class="rb-block"><div class="rb-label">Next Release</div>'
        f'<div class="rb-val">{h(info["release_str"])}</div></div>'
        f'<div class="rb-sep"></div>'
        f'<div class="rb-block"><div class="rb-label">Code Freeze</div>'
        f'<div class="rb-val" style="color:#dc2626;">{h(info["freeze_str"])}</div></div>'
        f'<div class="rb-sep"></div>'
        f'<div class="rb-block"><div class="rb-label">Tracking</div>'
        f'<div class="rb-val">{h(info["display"])}</div></div>'
        f'<div style="margin-left:auto;">'
        f'<span class="freeze-chip {chip_cls}">{chip_txt}</span>'
        f'</div>'
        f'</div>'
    )

def h(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")

def format_who(name: str) -> str:
    """Format 'First Last Name' → 'F. Last'"""
    if not name or name == "Unassigned":
        return "Unassigned"
    parts = name.strip().split()
    if len(parts) >= 2:
        return f"{parts[0][0]}. {parts[-1]}"
    return name

def ticket_row(issue: dict, css_class: str, pill_text: str = None) -> str:
    key      = issue["key"]
    summary  = issue["fields"]["summary"]
    assignee = issue["fields"].get("assignee") or {}
    who      = format_who(assignee.get("displayName", "Unassigned"))
    jira_url = f"https://{JIRA_HOST}/browse/{key}"
    right    = (
        f'<span class="pill pill-green">{h(pill_text)}</span>' if pill_text
        else f'<span class="ticket-who">{h(who)}</span>'
    )
    return (
        f'<div class="ticket {css_class}">'
        f'<span class="ticket-key"><a href="{jira_url}" target="_blank">{h(key)}</a></span>'
        f'<span class="ticket-sum">{h(summary)}</span>'
        f'{right}'
        f'</div>'
    )

def ticket_section(title: str, issues: list, css_class: str, limit: int = 6, pill: str = None) -> str:
    if not issues:
        return ""
    rows = "".join(ticket_row(i, css_class, pill_text=(
        i["fields"]["status"]["name"] if pill == "status" else pill
    )) for i in issues[:limit])
    more = (
        f'<div style="font-size:0.72rem;color:#94a3b8;margin-top:4px;">+{len(issues)-limit} more</div>'
        if len(issues) > limit else ""
    )
    return f'<div class="divider"></div><div class="section-title">{title}</div><div class="ticket-list">{rows}{more}</div>'

def stat_box(value: int, label: str, color: str, prev: int = None) -> str:
    if prev is None:
        delta_html = ""
    elif value > prev:
        delta_html = f'<div style="font-size:0.65rem;color:#16a34a;margin-top:2px;">+{value-prev} &uarr; (was {prev})</div>'
    elif value < prev:
        delta_html = f'<div style="font-size:0.65rem;color:#16a34a;margin-top:2px;">{value-prev} &darr; (was {prev})</div>'
    else:
        delta_html = f'<div style="font-size:0.65rem;color:#6b7280;margin-top:2px;">no change</div>'
    return (
        f'<div class="stat-box">'
        f'<div class="num {color}">{value}</div>'
        f'<div class="lbl">{h(label)}</div>'
        f'{delta_html}'
        f'</div>'
    )

def risk_badge(project: str, pct: int, in_prog: int) -> tuple:
    """Returns (text, css_class)"""
    if PROJECT_META[project]["mvp_label"]:
        if pct >= 80:
            return "&#x1F7E2; On Schedule", "badge-green"
        elif pct >= 55:
            return "&#x1F7E1; On Track", "badge-yellow"
        else:
            return "&#x1F534; At Risk", "badge-critical"
    else:
        if in_prog >= 5:
            return "&#x1F7E2; Healthy", "badge-green"
        elif in_prog > 0:
            return "&#x1F7E1; On Track", "badge-yellow"
        else:
            return "&#x26AA; Slow", "badge-blue"

def mvp_progress_bar(bar_label: str, done: int, total: int, prev_done: int = None, prev_total: int = None) -> str:
    pct   = round(done / total * 100) if total else 0
    color = "fill-green" if pct >= 70 else ("fill-orange" if pct >= 40 else "fill-red")
    trend_color = "#d97706"
    if prev_done is not None and prev_total is not None:
        prev_pct = round(prev_done / prev_total * 100) if prev_total else 0
        trend    = "&#x25B2;" if pct > prev_pct else ("&#x25BC;" if pct < prev_pct else "&#x2192;")
        if pct > prev_pct:
            trend_color = "#16a34a"
        right = (
            f'<div style="display:flex;gap:12px;align-items:center;">'
            f'<span style="font-size:0.72rem;color:#6b7280;">Last week: <strong>{prev_pct}%</strong></span>'
            f'<span style="font-weight:800;color:{trend_color};font-size:1rem;">This week: {pct}% {trend}</span>'
            f'</div>'
        )
    else:
        right = f'<span>{pct}% ({done}/{total})</span>'
    return (
        f'<div class="progress-wrap">'
        f'<div class="progress-label"><span>{h(bar_label)}</span>{right}</div>'
        f'<div class="progress-bar"><div class="progress-fill {color}" style="width:{pct}%"></div></div>'
        f'</div>'
    )

def project_card(project: str, issues: list, prev: dict = None, mvp_total: int = None,
                 lookahead_counts: dict = None, backlog_total: int = None,
                 overall_done: int = None, mobile_issues: list = None) -> str:
    meta    = PROJECT_META[project]
    buckets = bucket_issues(issues)
    done    = len(buckets["done"])
    in_prog = len(buckets["inprogress"])
    in_rev  = len(buckets["review"])
    open_   = len(buckets["open"])
    aband   = len(buckets["abandoned"])
    total   = done + in_prog + in_rev + open_ + aband

    p = prev or {}
    badge_text, badge_cls = risk_badge(project, round(done / (mvp_total or total) * 100) if (mvp_total or total) else 0, in_prog)

    # Sub-header text
    if meta["mvp_label"]:
        mvp_name = release_label_display(active_mvp_label())
        sub = meta["sub"].format(total=mvp_total or total, mvp_name=mvp_name)
        if overall_done is not None:
            sub += f' &middot; <span style="color:#475569;font-weight:600;">{overall_done} total LEF done</span>'
    elif "{backlog}" in meta["sub"]:
        sub = meta["sub"].format(backlog=backlog_total if backlog_total is not None else total)
    else:
        sub = meta["sub"]

    # Stat boxes — LEF gets 5 (with In Review), LEM/LRF get 4 (In Review merged into In Progress)
    if meta["mvp_label"]:
        stats_html = (
            f'<div class="stats">'
            + stat_box(done,    meta["done_label"],  "num-green",  p.get("done"))
            + stat_box(in_prog, "In Progress",        "num-blue",   p.get("inprogress"))
            + stat_box(in_rev,  "In Review",          "num-blue",   p.get("review"))
            + stat_box(open_,   meta["open_label"],   "num-orange", p.get("open"))
            + stat_box(aband,   "Abandoned",          "num-gray",   p.get("abandoned"))
            + f'</div>'
        )
    else:
        combined_prog = in_prog + in_rev
        prev_prog     = (p.get("inprogress", 0) or 0) + (p.get("review", 0) or 0) if p else None
        stats_html = (
            f'<div class="stats">'
            + stat_box(done,         meta["done_label"],  "num-green",  p.get("done") if p else None)
            + stat_box(combined_prog,"In Progress",        "num-blue",   prev_prog if p else None)
            + stat_box(open_,        meta["open_label"],  "num-orange", p.get("open") if p else None)
            + stat_box(aband,        "Abandoned",         "num-gray",   p.get("abandoned") if p else None)
            + f'</div>'
        )

    # Progress bar
    if meta["mvp_label"] and mvp_total:
        prev_done  = p.get("done") if p else None
        progress   = mvp_progress_bar(f"{mvp_name} Completion", done, mvp_total, prev_done, mvp_total)
    elif not meta["mvp_label"] and total:
        prev_done  = p.get("done") if p else None
        progress   = mvp_progress_bar("Overall Completion", done, total, prev_done, p.get("total") if p else None)
    else:
        progress = ""

    # Ticket sections — no "Open/Not Started" list; done items show pill
    body = ""
    body += ticket_section("In Progress", buckets["inprogress"], "inprogress")

    # Always show In Review / Testing — show placeholder if empty
    if buckets["review"]:
        body += ticket_section("In Review / Testing", buckets["review"], "done", pill="status")
    else:
        body += (
            f'<div class="divider"></div>'
            f'<div class="section-title">In Review / Testing</div>'
            f'<div style="font-size:0.78rem;color:#94a3b8;padding:6px 0 10px 0;">None currently in review</div>'
        )

    body += ticket_section(meta["completed_label"], buckets["done"], "done", limit=6, pill="Done")

    if meta["mvp_label"] and mobile_issues:
        mobile_b = bucket_issues(mobile_issues)
        body += (
            f'<div class="divider"></div>'
            f'<div class="section-title" style="color:#1d4ed8;">&#x1F4F1; Mobile Tracker</div>'
            f'<div class="alert alert-yellow">'
            f'<span class="alert-icon">&#x1F4CB;</span>'
            f'<span><strong>{len(mobile_issues)} Mobile-labelled tickets</strong> &mdash; '
            f'{len(mobile_b["done"])} done, '
            f'{len(mobile_b["inprogress"]) + len(mobile_b["review"])} active, '
            f'{len(mobile_b["open"])} not started.</span>'
            f'</div>'
        )

    if meta["mvp_label"] and lookahead_counts:
        rows = "".join(
            f'<div class="ticket open">'
            f'<span class="pill pill-blue" style="min-width:95px;text-align:center;">{h(release_label_display(label))}</span>'
            f'<span class="ticket-sum">{count} tagged tickets</span>'
            f'</div>'
            for label, count in lookahead_counts.items()
        )
        body += (
            f'<div class="divider"></div>'
            f'<div class="section-title" style="color:#7c3aed;">'
            f'&#x1F52D; LEF Release Label Outlook</div>'
            f'<div class="alert alert-yellow">'
            f'<span class="alert-icon">&#x1F4CB;</span>'
            f'<span><strong>{h(mvp_name)}</strong> is the active LEF focus. Future tagged counts are shown below for staffing look-ahead.</span>'
            f'</div>'
            f'<div class="ticket-list">{rows}</div>'
        )

    return (
        f'<div class="card" style="border-top: 4px solid {meta["color"]}">'
        f'<div class="project-header">'
        f'<div>'
        f'<div class="project-name">{h(meta["label"])} <span style="font-weight:400;color:#6b7280;">&middot; {h(meta["desc"])}</span></div>'
        f'<div class="project-sub">{sub}</div>'
        f'</div>'
        f'<span class="badge {badge_cls}" style="margin-left:auto;">{badge_text}</span>'
        f'</div>'
        f'{stats_html}'
        f'{progress}'
        f'{body}'
        f'</div>'
    )

# ---------------------------------------------------------------------------
# Week-over-week stats persistence
# ---------------------------------------------------------------------------
STATS_FILE = "stats.json"

def load_stats() -> dict:
    try:
        with open(STATS_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_stats(slug: str, per_project: dict):
    data = load_stats()
    data[slug] = per_project
    with open(STATS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def get_prev_stats(slug: str) -> tuple:
    """Return (prev_slug, per-project bucket counts) from the most recent previous run."""
    data = load_stats()
    dates = sorted(k for k in data if k < slug)
    if not dates:
        return None, {}
    return dates[-1], data[dates[-1]]

def actions_card(all_issues: dict, mvp_total: int, lookahead_counts: dict, mobile_issues: list) -> str:
    lef_b   = bucket_issues(all_issues["LEF"])
    lem_b   = bucket_issues(all_issues["LEM"])
    lrf_b   = bucket_issues(all_issues["LRF"])
    lef_open = len(lef_b["open"])
    lef_done = len(lef_b["done"])
    lem_done = len(lem_b["done"])
    lef_pct  = round(lef_done / mvp_total * 100) if mvp_total else 0
    mvp_name = active_mvp_label()

    items = []
    # LEF open risk
    if lef_open > 0:
        items.append(
            f'<strong>[LEF &mdash; URGENT]</strong> {lef_open} unstarted '
            f'<code>{mvp_name}</code> tickets with '
            f'{"~" if lef_pct < 70 else ""}{100 - lef_pct}% still to go. '
            f'Assign owners or cut scope this week.'
        )
    if lookahead_counts:
        forecast = ", ".join(
            f'{release_label_display(label)}: {count}'
            for label, count in lookahead_counts.items()
        )
        items.append(
            f'<strong>[LEF &mdash; Look Ahead]</strong> Tagged release counts &mdash; {h(forecast)}.'
        )
    if mobile_issues:
        mobile_b = bucket_issues(mobile_issues)
        items.append(
            f'<strong>[LEF &mdash; Mobile]</strong> {len(mobile_issues)} tickets tagged {h(LEF_MOBILE_LABEL)} &mdash; '
            f'{len(mobile_b["inprogress"]) + len(mobile_b["review"])} active, '
            f'{len(mobile_b["open"])} not started.'
        )
    # LEM done items
    if lem_done > 0:
        items.append(
            f'<strong>[LEM]</strong> {lem_done} tickets completed this month. '
            f'{len(lem_b["inprogress"]) + len(lem_b["review"])} still active.'
        )
    # LRF
    lrf_prog = len(lrf_b["inprogress"]) + len(lrf_b["review"])
    if lrf_prog > 0:
        items.append(
            f'<strong>[LRF]</strong> {lrf_prog} items in flight, '
            f'{len(lrf_b["done"])} completed overall.'
        )

    lis = "".join(
        f'<li><span class="action-num">{i+1}</span><div class="action-text">{item}</div></li>'
        for i, item in enumerate(items)
    )
    return (
        f'<div class="card two-col" style="border-top:4px solid #6366f1">'
        f'<div class="project-header"><div class="project-name">&#x26A1; Actions Required</div></div>'
        f'<ul class="action-list">{lis}</ul>'
        f'</div>'
    )

def roadmap_card() -> str:
    try:
        with open("roadmap.json") as f:
            entries = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        entries = []
    rows = "".join(
        f'<div class="ticket open">'
        f'<span class="pill {e["pill"]}" style="min-width:55px;text-align:center;">{h(e["month"])}</span>'
        f'<span class="ticket-sum">{h(e["items"])}</span>'
        f'</div>'
        for e in entries
    )
    return (
        f'<div class="card" style="border-top:4px solid #6366f1">'
        f'<div class="project-header"><div class="project-name">&#x1F5D3;&#xFE0F; Roadmap Snapshot</div></div>'
        f'<div class="ticket-list">{rows}</div>'
        f'</div>'
    )

def what_changed_card(date_str: str, all_issues: dict, prev_stats: dict, mvp_total: int, prev_slug: str = None) -> str:
    if not prev_stats or not prev_slug:
        return ""

    # Format prev date slug YYMMDD → "May 21"
    try:
        prev_dt   = datetime.datetime.strptime(prev_slug, "%y%m%d")
        prev_label = prev_dt.strftime("%B %-d")
    except ValueError:
        prev_label = prev_slug

    curr_label = date_str  # already "May 21, 2026"

    COLOR = {
        "LEF": "#dc2626", "LEM": "#d97706", "LRF": "#16a34a",
    }
    TH = 'style="padding:8px 12px;text-align:{align};font-size:0.68rem;color:#64748b;text-transform:uppercase;letter-spacing:0.5px;"'
    TD = 'style="padding:8px 12px;"'

    def change_pill(curr, prev_val, lower_is_better=False):
        if prev_val is None:
            return '<span class="change-pill change-new">New &#x2605;</span>'
        diff = curr - prev_val
        if diff == 0:
            return '<span class="change-pill change-flat">no change</span>'
        pct = round(abs(diff) / prev_val * 100) if prev_val else 0
        arrow = "&#x2191;" if diff > 0 else "&#x2193;"
        sign  = "+" if diff > 0 else ""
        good  = (diff < 0) if lower_is_better else (diff > 0)
        cls   = "change-up" if good else "change-down"
        return f'<span class="change-pill {cls}">{sign}{pct}% {arrow}</span>'

    rows = ""
    alt  = False
    def row(proj, metric, prev_val, curr_val, note="", lower_is_better=False):
        nonlocal alt, rows
        bg   = ' style="background:#fafafa;"' if alt else ""
        pill = change_pill(curr_val, prev_val, lower_is_better)
        rows += (
            f'<tr{bg}>'
            f'<td {TD} style="padding:8px 12px;font-weight:700;color:{COLOR[proj]};">{proj}</td>'
            f'<td {TD}>{h(metric)}</td>'
            f'<td {TD} style="padding:8px 12px;text-align:center;color:#64748b;">{prev_val if prev_val is not None else "&mdash;"}</td>'
            f'<td {TD} style="padding:8px 12px;text-align:center;font-weight:700;">{curr_val}</td>'
            f'<td {TD} style="padding:8px 12px;text-align:center;">{pill}</td>'
            f'<td {TD} style="padding:8px 12px;color:#6b7280;font-size:0.77rem;">{note}</td>'
            f'</tr>'
        )
        alt = not alt

    for proj in PROJECTS:
        b    = bucket_issues(all_issues[proj])
        prev = prev_stats.get(proj, {})
        done = len(b["done"])
        prog = len(b["inprogress"]) + len(b["review"])
        open_ = len(b["open"])
        if proj == "LEF":
            pct_curr = round(done / mvp_total * 100) if mvp_total else 0
            pct_prev = round((prev.get("done") or 0) / mvp_total * 100) if mvp_total else None
            row("LEF", f"{release_label_display(active_mvp_label())} — Completed",
                prev.get("done"), done,
                f'{pct_prev}% &rarr; {pct_curr}% complete' if pct_prev is not None else f'{pct_curr}% complete')
            row("LEF", "Not Started",       prev.get("open"),      open_,  "", lower_is_better=True)
            row("LEF", "In Review/Testing", prev.get("review"),    len(b["review"]))
        else:
            row(proj, "Done This Month", prev.get("done"),      done)
            row(proj, "In Progress",     prev.get("inprogress"), prog)

    headers = (
        f'<tr style="background:#f0f2f5;">'
        f'<th {TH.format(align="left")} style="width:55px;">Board</th>'
        f'<th {TH.format(align="left")}>Metric</th>'
        f'<th {TH.format(align="center")}>{h(prev_label)}</th>'
        f'<th {TH.format(align="center")}>{h(curr_label)}</th>'
        f'<th {TH.format(align="center")}>Change</th>'
        f'<th {TH.format(align="left")}>Notes</th>'
        f'</tr>'
    )
    return (
        f'<div class="card full" style="border-top:4px solid #6366f1;margin-top:0;">'
        f'<div class="project-header" style="margin-bottom:4px;">'
        f'<div>'
        f'<div class="project-name">&#x1F504; What Changed This Week</div>'
        f'<div class="project-sub">{h(prev_label)} &rarr; {h(date_str)}</div>'
        f'</div></div>'
        f'<table class="wow-table" style="width:100%;border-collapse:collapse;margin-top:8px;">'
        f'<thead>{headers}</thead><tbody>{rows}</tbody>'
        f'</table>'
        f'</div>'
    )

def render_html(all_issues: dict, date_str: str, today: datetime.date = None,
                prev_stats: dict = None, prev_slug: str = None, mvp_totals: dict = None) -> str:
    if today is None:
        today = datetime.date.today()
    label     = active_mvp_label(today)
    rel_info  = next_release_info(today)
    banner    = release_banner_html(rel_info)
    boards    = " &middot; ".join(PROJECTS)
    prev_stats  = prev_stats  or {}
    mvp_totals  = mvp_totals  or {}

    def _card(proj):
        p = prev_stats.get(proj)
        return project_card(
            proj, all_issues[proj],
            prev=p,
            mvp_total=mvp_totals.get(proj),
            lookahead_counts=mvp_totals.get("LEF_lookahead_counts") if proj == "LEF" else None,
            backlog_total=mvp_totals.get("LEM_backlog") if proj == "LEM" else None,
            overall_done=mvp_totals.get("LEF_overall_done") if proj == "LEF" else None,
            mobile_issues=mvp_totals.get("LEF_mobile_issues") if proj == "LEF" else None,
        )

    cards      = "\n".join(_card(proj) for proj in PROJECTS)
    lef_mvp    = mvp_totals.get("LEF", 0)
    bottom_row = actions_card(
        all_issues,
        lef_mvp,
        mvp_totals.get("LEF_lookahead_counts", {}),
        mvp_totals.get("LEF_mobile_issues", []),
    ) + "\n" + roadmap_card()
    wow        = what_changed_card(date_str, all_issues, prev_stats, lef_mvp, prev_slug=prev_slug)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1.0"/>
<title>Literacy Weekly Project Dashboard &mdash; {h(date_str)}</title>
<style>
{CSS + RELEASE_BANNER_CSS}
</style>
</head>
<body>
<header>
  <div>
    <h1>&#x1F4DA; Literacy Weekly Project Dashboard</h1>
    <div style="font-size:0.85rem;opacity:0.85;margin-top:4px;">Boards: {boards} &nbsp;&middot;&nbsp; Tracking: <strong>{h(rel_info.get("display", label))}</strong></div>
  </div>
  <div class="meta">
    <div>Week of {h(date_str)}</div>
    <div>Auto-generated from Jira</div>
  </div>
</header>

{banner}

<div class="grid">
{cards}
</div>

<div class="grid">
{bottom_row}
</div>

<div class="grid" style="margin-top:0;">
{wow}
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

    entries = {
        href: title
        for href, title in re.findall(r'<li><a href="([^"]+)">([^<]+)</a></li>', content)
    }
    entries[new_filename] = f"{date_str} Weekly Dashboard"

    rows = "".join(
        f'      <li><a href="{href}">{h(title)}</a></li>\n'
        for href, title in sorted(entries.items(), reverse=True)
    )
    content = (
        "<!doctype html>\n<html lang='en'>\n<head><meta charset='utf-8'/>"
        "<meta name='viewport' content='width=device-width, initial-scale=1' />"
        "<title>Literacy Weekly Project Dashboard</title></head>\n<body>\n<h1>Literacy Weekly Project Dashboard</h1>\n"
        f"<ul>\n{rows}</ul>\n</body>\n</html>\n"
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

    try:
        today = parse_dashboard_date(DATE_OVERRIDE)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
    date_str   = today.strftime("%B %-d, %Y")
    file_slug  = today.strftime("%y%m%d")
    filename   = f"{file_slug}_weekly_dashboard.html"
    label      = active_mvp_label(today)
    prev_slug, prev_stats = get_prev_stats(file_slug)

    try:
        validate_jira_access()

        print(f"Fetching Jira data for {', '.join(PROJECTS)} ...")
        all_issues = {}
        for proj in PROJECTS:
            all_issues[proj] = get_active_sprint_issues(proj, today=today)

        validate_issue_counts(all_issues, prev_stats)

        # Fetch LEF release and mobile tracking counts
        mvp_totals: dict = {}
        print(f"Fetching {label} total count for LEF...")
        lef_label_counts = fetch_lef_release_counts()
        mvp_totals["LEF"] = lef_label_counts.get(label, len(all_issues["LEF"]))
        mvp_totals["LEF_lookahead_counts"] = {
            release["label"]: lef_label_counts[release["label"]]
            for release in LEF_LOOKAHEAD_RELEASES
            if release["label"] in lef_label_counts
        }
        mvp_totals["LEF_overall_done"] = jira_total(
            f'project = LEF AND status = "Done"{lef_issue_type_clause()}'
        )
        print(f"  LEF overall done total: {mvp_totals['LEF_overall_done']}")
        mvp_totals["LEF_mobile_issues"] = fetch_lef_mobile_issues()

        # Fetch LEM total backlog (all non-abandoned tickets)
        print("Fetching LEM backlog total...")
        mvp_totals["LEM_backlog"] = jira_total(
            "project = LEM AND statusCategory != Done AND status != Abandoned"
        )
        print(f"  LEM backlog total: {mvp_totals['LEM_backlog']}")
    except JiraQueryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)

    html = render_html(all_issues, date_str, today, prev_stats=prev_stats, prev_slug=prev_slug, mvp_totals=mvp_totals)

    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"Generated {filename}")

    # Save current stats for next week's deltas
    current_stats = {}
    for proj, issues in all_issues.items():
        b = bucket_issues(issues)
        current_stats[proj] = {
            "done": len(b["done"]), "inprogress": len(b["inprogress"]),
            "review": len(b["review"]), "open": len(b["open"]),
            "abandoned": len(b["abandoned"]),
            "total": sum(len(v) for v in b.values()),
        }
    save_stats(file_slug, current_stats)
    print(f"Saved stats snapshot → {STATS_FILE}")

    update_index(filename, date_str)

if __name__ == "__main__":
    main()
