# GitHub Repo Audit Skill — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code skill that audits one GitHub repo's PR throughput, contributors, and hotfix/revert counts, and renders the result as a self-contained HTML dashboard artifact.

**Architecture:** Approach A — a stdlib-only Python script (`scripts/audit.py`) shells out to the `gh` CLI, classifies and buckets PRs in pure (testable) functions, and prints one JSON object. `SKILL.md` orchestrates: run script → fill `templates/dashboard.html` with the JSON → publish as an Artifact. All numeric logic lives in code and is unit-tested; Claude never tallies by hand.

**Tech Stack:** Python 3 (stdlib only — `subprocess`, `json`, `datetime`, `argparse`, `unittest`), the `gh` CLI, HTML/CSS/vanilla-JS for the dashboard.

## Global Constraints

- Python **standard library only** — no `pip install`, no third-party packages (including in tests; use `unittest`, not `pytest`).
- The **only** network/IO boundary is the `gh` CLI. Pure functions must never call `gh`; tests feed fixture dicts shaped like `gh --json` output.
- `now` (current time) is always **injected** as a parameter into pure functions — never call `datetime.now()` inside testable logic.
- Repo identifier format is `owner/name`.
- Hotfix rule: head branch starts with `hotfix/` (case-insensitive).
- Revert rule (match ANY): title starts with `Revert "`, OR branch starts with `revert/` or `revert-`, OR a label lowercases to `revert`.
- `dashboard.html` must be fully self-contained: inline CSS + inline JS only, no external/CDN assets (Artifact CSP forbids them).
- Default window: 4 weeks + 3 months.
- A `gh` failure must surface as a non-zero exit with a clear stderr message — never emit fabricated numbers.

---

### Task 1: PR classification

**Files:**
- Create: `scripts/audit.py`
- Test: `tests/test_classify.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces:
  - Module-level constants `HOTFIX_PREFIX = "hotfix/"`, `REVERT_TITLE_PREFIX = 'Revert "'`, `REVERT_LABEL = "revert"`.
  - `classify(pr: dict) -> dict` returning `{"is_hotfix": bool, "is_revert": bool}`. `pr` has optional keys `title` (str), `headRefName` (str), `labels` (list of `{"name": str}`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_classify.py
import unittest
from scripts.audit import classify


def pr(title="x", branch="feature/x", labels=None):
    return {"title": title, "headRefName": branch, "labels": labels or []}


class TestClassify(unittest.TestCase):
    def test_hotfix_branch(self):
        self.assertTrue(classify(pr(branch="hotfix/payment-crash"))["is_hotfix"])

    def test_hotfix_case_insensitive(self):
        self.assertTrue(classify(pr(branch="HotFix/Thing"))["is_hotfix"])

    def test_plain_branch_is_not_hotfix(self):
        self.assertFalse(classify(pr(branch="feature/login"))["is_hotfix"])

    def test_revert_by_title(self):
        self.assertTrue(classify(pr(title='Revert "Add login"'))["is_revert"])

    def test_revert_by_branch_slash(self):
        self.assertTrue(classify(pr(branch="revert/login"))["is_revert"])

    def test_revert_by_branch_dash(self):
        self.assertTrue(classify(pr(branch="revert-abc123-main"))["is_revert"])

    def test_revert_by_label(self):
        self.assertTrue(classify(pr(labels=[{"name": "Revert"}]))["is_revert"])

    def test_plain_pr_is_neither(self):
        c = classify(pr())
        self.assertFalse(c["is_hotfix"])
        self.assertFalse(c["is_revert"])

    def test_both_hotfix_and_revert(self):
        c = classify(pr(title='Revert "x"', branch="hotfix/x"))
        self.assertTrue(c["is_hotfix"])
        self.assertTrue(c["is_revert"])

    def test_missing_fields_safe(self):
        c = classify({})
        self.assertFalse(c["is_hotfix"])
        self.assertFalse(c["is_revert"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_classify -v`
Expected: FAIL — `ModuleNotFoundError` or `ImportError: cannot import name 'classify'`.

(Note: there must be an empty `tests/__init__.py` and `scripts/__init__.py` so `from scripts.audit import ...` resolves. Create both as empty files in this step if missing.)

- [ ] **Step 3: Write minimal implementation**

```python
# scripts/audit.py
"""Audit one GitHub repo's PR activity. Stdlib only."""

HOTFIX_PREFIX = "hotfix/"
REVERT_TITLE_PREFIX = 'Revert "'
REVERT_LABEL = "revert"


def classify(pr):
    branch = (pr.get("headRefName") or "").lower()
    title = pr.get("title") or ""
    labels = [(l.get("name") or "").lower() for l in (pr.get("labels") or [])]
    is_hotfix = branch.startswith(HOTFIX_PREFIX)
    is_revert = (
        title.startswith(REVERT_TITLE_PREFIX)
        or branch.startswith("revert/")
        or branch.startswith("revert-")
        or REVERT_LABEL in labels
    )
    return {"is_hotfix": is_hotfix, "is_revert": is_revert}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_classify -v`
Expected: PASS (10 tests OK).

- [ ] **Step 5: Commit**

```bash
git add scripts/audit.py scripts/__init__.py tests/__init__.py tests/test_classify.py
git commit -m "feat: PR hotfix/revert classification with tests"
```

---

### Task 2: Date helpers, bucketing, contributors, report assembly

**Files:**
- Modify: `scripts/audit.py`
- Test: `tests/test_report.py`

**Interfaces:**
- Consumes: `classify` from Task 1.
- Produces:
  - `parse_dt(s: str | None) -> datetime | None` — parses an ISO8601 string (trailing `Z` allowed); `None`/empty → `None`.
  - `week_start(d: date) -> date` — Monday of `d`'s ISO week.
  - `month_key(d: date) -> str` — `"YYYY-MM"`.
  - `bucket_by_week(prs, now: datetime, weeks=4) -> list[dict]` — chronological list of `{"week_start","opened","closed","merged"}`.
  - `bucket_by_month(prs, now: datetime, months=3) -> list[dict]` — chronological list of `{"month","opened","closed","merged"}`.
  - `contributors(prs) -> list[dict]` — `{"login","count"}` sorted by count desc then login; null author → `"(unknown)"`.
  - `build_report(prs, repo: str, now: datetime, weeks=4, months=3) -> dict` — full JSON-shaped report (see spec's JSON contract).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_report.py
import unittest
from datetime import datetime, timezone
from scripts.audit import (
    parse_dt, week_start, month_key,
    bucket_by_week, bucket_by_month, contributors, build_report,
)

# Fixed "now": Friday 2026-06-26. Current ISO week starts Mon 2026-06-22.
NOW = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)


def mkpr(login, created, closed=None, merged=None, branch="feature/x",
         title="x", labels=None):
    return {
        "author": {"login": login} if login else None,
        "createdAt": created, "closedAt": closed, "mergedAt": merged,
        "headRefName": branch, "title": title, "labels": labels or [],
    }


class TestHelpers(unittest.TestCase):
    def test_parse_dt_z(self):
        self.assertEqual(parse_dt("2026-06-26T00:00:00Z").year, 2026)

    def test_parse_dt_none(self):
        self.assertIsNone(parse_dt(None))
        self.assertIsNone(parse_dt(""))

    def test_week_start_is_monday(self):
        self.assertEqual(week_start(datetime(2026, 6, 26).date()).isoformat(), "2026-06-22")

    def test_month_key(self):
        self.assertEqual(month_key(datetime(2026, 6, 26).date()), "2026-06")


class TestBuckets(unittest.TestCase):
    def test_weekly_opened_closed_merged(self):
        prs = [mkpr("a", "2026-06-23T00:00:00Z", "2026-06-24T00:00:00Z", "2026-06-24T00:00:00Z")]
        wk = bucket_by_week(prs, NOW, weeks=4)
        self.assertEqual(len(wk), 4)
        self.assertEqual(wk[-1]["week_start"], "2026-06-22")
        self.assertEqual(wk[-1]["opened"], 1)
        self.assertEqual(wk[-1]["closed"], 1)
        self.assertEqual(wk[-1]["merged"], 1)

    def test_flow_not_cohort(self):
        # opened in oldest week, merged in newest week -> counted separately
        prs = [mkpr("a", "2026-06-01T00:00:00Z", "2026-06-24T00:00:00Z", "2026-06-24T00:00:00Z")]
        wk = bucket_by_week(prs, NOW, weeks=4)
        self.assertEqual(wk[0]["opened"], 1)
        self.assertEqual(wk[0]["merged"], 0)
        self.assertEqual(wk[-1]["merged"], 1)

    def test_outside_window_excluded(self):
        prs = [mkpr("a", "2026-01-01T00:00:00Z")]
        wk = bucket_by_week(prs, NOW, weeks=4)
        self.assertEqual(sum(b["opened"] for b in wk), 0)

    def test_monthly(self):
        prs = [mkpr("a", "2026-05-10T00:00:00Z")]
        mo = bucket_by_month(prs, NOW, months=3)
        self.assertEqual([m["month"] for m in mo], ["2026-04", "2026-05", "2026-06"])
        self.assertEqual(mo[1]["opened"], 1)


class TestContributors(unittest.TestCase):
    def test_counts_and_sort(self):
        prs = [mkpr("a", "2026-06-23T00:00:00Z"),
               mkpr("b", "2026-06-23T00:00:00Z"),
               mkpr("a", "2026-06-23T00:00:00Z")]
        c = contributors(prs)
        self.assertEqual(c[0], {"login": "a", "count": 2})
        self.assertEqual(c[1], {"login": "b", "count": 1})

    def test_null_author(self):
        c = contributors([mkpr(None, "2026-06-23T00:00:00Z")])
        self.assertEqual(c[0]["login"], "(unknown)")


class TestBuildReport(unittest.TestCase):
    def test_shape_and_totals(self):
        prs = [
            mkpr("a", "2026-06-23T00:00:00Z", "2026-06-24T00:00:00Z", "2026-06-24T00:00:00Z",
                 branch="hotfix/x"),
            mkpr("b", "2026-06-23T00:00:00Z", title='Revert "y"'),
        ]
        r = build_report(prs, "owner/name", NOW)
        self.assertEqual(r["repo"], "owner/name")
        self.assertEqual(r["totals"]["opened"], 2)
        self.assertEqual(r["totals"]["closed"], 1)
        self.assertEqual(r["totals"]["merged"], 1)
        self.assertEqual(r["totals"]["hotfix"], 1)
        self.assertEqual(r["totals"]["revert"], 1)
        self.assertEqual(r["totals"]["contributors"], 2)
        self.assertIn("weekly", r)
        self.assertIn("monthly", r)
        self.assertIn("since", r["window"])

    def test_empty_input(self):
        r = build_report([], "owner/name", NOW)
        self.assertEqual(r["totals"]["opened"], 0)
        self.assertEqual(r["contributors"], [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_report -v`
Expected: FAIL — `ImportError: cannot import name 'parse_dt'`.

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/audit.py`:

```python
from datetime import datetime, timedelta, date


def parse_dt(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def week_start(d):
    return d - timedelta(days=d.weekday())


def month_key(d):
    return f"{d.year:04d}-{d.month:02d}"


def _month_list(now, months):
    out = []
    for i in range(months - 1, -1, -1):
        yy, mm = now.year, now.month - i
        while mm <= 0:
            mm += 12
            yy -= 1
        out.append(f"{yy:04d}-{mm:02d}")
    return out


def bucket_by_week(prs, now, weeks=4):
    cur = week_start(now.date())
    starts = [cur - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    idx = {s: {"week_start": s.isoformat(), "opened": 0, "closed": 0, "merged": 0}
           for s in starts}
    valid = set(starts)
    for pr in prs:
        for field, key in (("createdAt", "opened"), ("closedAt", "closed"),
                           ("mergedAt", "merged")):
            dt = parse_dt(pr.get(field))
            if dt and week_start(dt.date()) in valid:
                idx[week_start(dt.date())][key] += 1
    return [idx[s] for s in starts]


def bucket_by_month(prs, now, months=3):
    keys = _month_list(now, months)
    valid = set(keys)
    idx = {k: {"month": k, "opened": 0, "closed": 0, "merged": 0} for k in keys}
    for pr in prs:
        for field, key in (("createdAt", "opened"), ("closedAt", "closed"),
                           ("mergedAt", "merged")):
            dt = parse_dt(pr.get(field))
            if dt and month_key(dt.date()) in valid:
                idx[month_key(dt.date())][key] += 1
    return [idx[k] for k in keys]


def contributors(prs):
    counts = {}
    for pr in prs:
        author = pr.get("author") or {}
        login = author.get("login") or "(unknown)"
        counts[login] = counts.get(login, 0) + 1
    items = [{"login": k, "count": v} for k, v in counts.items()]
    items.sort(key=lambda x: (-x["count"], x["login"]))
    return items


def build_report(prs, repo, now, weeks=4, months=3):
    weekly = bucket_by_week(prs, now, weeks)
    monthly = bucket_by_month(prs, now, months)
    since = min(
        date.fromisoformat(weekly[0]["week_start"]),
        date.fromisoformat(monthly[0]["month"] + "-01"),
    )
    in_window = [
        pr for pr in prs
        if (parse_dt(pr.get("createdAt")) or now).date() >= since
    ]
    contribs = contributors(in_window)
    totals = {
        "opened": len(in_window),
        "closed": sum(1 for pr in in_window if pr.get("closedAt")),
        "merged": sum(1 for pr in in_window if pr.get("mergedAt")),
        "hotfix": sum(1 for pr in in_window if classify(pr)["is_hotfix"]),
        "revert": sum(1 for pr in in_window if classify(pr)["is_revert"]),
        "contributors": len(contribs),
    }
    return {
        "repo": repo,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": {"weeks": weeks, "months": months, "since": since.isoformat()},
        "weekly": weekly,
        "monthly": monthly,
        "contributors": contribs,
        "totals": totals,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_report -v`
Expected: PASS (all tests OK).

- [ ] **Step 5: Commit**

```bash
git add scripts/audit.py tests/test_report.py
git commit -m "feat: date bucketing, contributors, report assembly with tests"
```

---

### Task 3: CLI entrypoint + gh boundary

**Files:**
- Modify: `scripts/audit.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `build_report` from Task 2.
- Produces:
  - `fetch_prs(repo: str, limit: int = 500) -> list[dict]` — runs `gh pr list`, raises `RuntimeError` on non-zero exit.
  - `main(argv=None, fetch=fetch_prs, now=None) -> int` — parses args, fetches, builds report, prints JSON to stdout, returns exit code. `fetch` and `now` are injectable for tests. On `RuntimeError`, prints message to stderr and returns `1`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main.py
import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from scripts.audit import main

NOW = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)

FAKE_PRS = [
    {"author": {"login": "a"}, "createdAt": "2026-06-23T00:00:00Z",
     "closedAt": "2026-06-24T00:00:00Z", "mergedAt": "2026-06-24T00:00:00Z",
     "headRefName": "hotfix/x", "title": "fix", "labels": []},
]


class TestMain(unittest.TestCase):
    def test_prints_valid_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["owner/name"], fetch=lambda repo, limit=500: FAKE_PRS, now=NOW)
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["repo"], "owner/name")
        self.assertEqual(data["totals"]["hotfix"], 1)

    def test_gh_failure_returns_1(self):
        def boom(repo, limit=500):
            raise RuntimeError("gh failed: not authenticated")
        err = io.StringIO()
        with redirect_stderr(err):
            code = main(["owner/name"], fetch=boom, now=NOW)
        self.assertEqual(code, 1)
        self.assertIn("not authenticated", err.getvalue())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m unittest tests.test_main -v`
Expected: FAIL — `ImportError: cannot import name 'main'`.

- [ ] **Step 3: Write minimal implementation**

Append to `scripts/audit.py`:

```python
import sys
import json
import argparse
import subprocess
from datetime import timezone

GH_FIELDS = "number,title,author,createdAt,closedAt,mergedAt,state,headRefName,labels"


def fetch_prs(repo, limit=500):
    cmd = ["gh", "pr", "list", "--repo", repo, "--state", "all",
           "--limit", str(limit), "--json", GH_FIELDS]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"gh failed: {result.stderr.strip()}")
    prs = json.loads(result.stdout or "[]")
    if len(prs) >= limit:
        print(f"warning: hit --limit {limit}; older PRs may be missing",
              file=sys.stderr)
    return prs


def main(argv=None, fetch=fetch_prs, now=None):
    parser = argparse.ArgumentParser(description="Audit a GitHub repo's PR activity.")
    parser.add_argument("repo", help="owner/name")
    parser.add_argument("--weeks", type=int, default=4)
    parser.add_argument("--months", type=int, default=3)
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args(argv)
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        prs = fetch(args.repo, limit=args.limit)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1
    report = build_report(prs, args.repo, now, args.weeks, args.months)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m unittest tests.test_main -v`
Expected: PASS (2 tests OK).

- [ ] **Step 5: Run the full suite + a real smoke test**

Run: `python3 -m unittest discover -s tests -v`
Expected: ALL tests PASS.

Run (real `gh`, pick any repo you can access):
`python3 scripts/audit.py cli/cli --weeks 2 --months 2 | head -30`
Expected: valid JSON with non-zero `totals`. If it errors, that's a real auth/access issue to fix — not a code bug to paper over.

- [ ] **Step 6: Commit**

```bash
git add scripts/audit.py tests/test_main.py
git commit -m "feat: gh fetch boundary + CLI entrypoint with tests"
```

---

### Task 4: HTML dashboard template

**Files:**
- Create: `templates/dashboard.html`
- Test: manual render check (no unit test — it's a static template; correctness is verified by rendering real data in Task 5).

**Interfaces:**
- Consumes: the JSON object from `build_report` (Task 2), injected at the single token `{{DATA_JSON}}`.
- Produces: a self-contained HTML page. Claude's only substitution is replacing `{{DATA_JSON}}` with the literal JSON; inline JS renders all sections from it.

- [ ] **Step 1: Create the template**

```html
<!-- templates/dashboard.html -->
<div id="app"></div>
<style>
  #app { font-family: -apple-system, system-ui, sans-serif; max-width: 880px;
         margin: 0 auto; padding: 24px; color: #1a1a1a; }
  h1 { font-size: 20px; margin: 0 0 4px; }
  .sub { color: #666; font-size: 13px; margin-bottom: 20px; }
  .cards { display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px; }
  .card { flex: 1 1 110px; border: 1px solid #e3e3e3; border-radius: 10px;
          padding: 12px 14px; }
  .card .n { font-size: 24px; font-weight: 600; }
  .card .l { font-size: 12px; color: #666; text-transform: uppercase;
             letter-spacing: .04em; }
  h2 { font-size: 15px; margin: 24px 0 8px; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th, td { text-align: left; padding: 6px 8px; border-bottom: 1px solid #eee; }
  th { color: #666; font-weight: 600; }
  td.num, th.num { text-align: right; font-variant-numeric: tabular-nums; }
  .bar { height: 8px; background: #2563eb; border-radius: 4px; }
  .wrap { overflow-x: auto; }
</style>
<script>
  const DATA = {{DATA_JSON}};
  const el = (t, p = {}, ...kids) => {
    const n = Object.assign(document.createElement(t), p);
    kids.forEach(k => n.append(k));
    return n;
  };
  const app = document.getElementById("app");
  const T = DATA.totals;
  app.append(el("h1", { textContent: "Repo Audit — " + DATA.repo }));
  app.append(el("div", { className: "sub",
    textContent: `Window since ${DATA.window.since} · generated ${DATA.generated_at}` }));

  const cards = el("div", { className: "cards" });
  [["Opened", T.opened], ["Closed", T.closed], ["Merged", T.merged],
   ["Hotfix", T.hotfix], ["Revert", T.revert], ["Contributors", T.contributors]]
    .forEach(([l, n]) => cards.append(
      el("div", { className: "card" },
        el("div", { className: "n", textContent: n }),
        el("div", { className: "l", textContent: l }))));
  app.append(cards);

  function flowTable(title, rows, labelKey, labelHead) {
    app.append(el("h2", { textContent: title }));
    const wrap = el("div", { className: "wrap" });
    const tbl = el("table");
    const head = el("tr");
    [labelHead, "Opened", "Closed", "Merged"].forEach((h, i) =>
      head.append(el("th", { textContent: h, className: i ? "num" : "" })));
    tbl.append(head);
    const max = Math.max(1, ...rows.map(r => r.opened));
    rows.forEach(r => {
      const tr = el("tr");
      tr.append(el("td", { textContent: r[labelKey] }));
      ["opened", "closed", "merged"].forEach(k =>
        tr.append(el("td", { className: "num", textContent: r[k] })));
      tbl.append(tr);
    });
    wrap.append(tbl);
    app.append(wrap);
  }
  flowTable("Weekly", DATA.weekly, "week_start", "Week of");
  flowTable("Monthly", DATA.monthly, "month", "Month");

  app.append(el("h2", { textContent: "Contributors" }));
  const ct = el("table");
  const ch = el("tr");
  ["Author", "PRs"].forEach((h, i) =>
    ch.append(el("th", { textContent: h, className: i ? "num" : "" })));
  ct.append(ch);
  DATA.contributors.forEach(c => {
    const tr = el("tr");
    tr.append(el("td", { textContent: c.login }));
    tr.append(el("td", { className: "num", textContent: c.count }));
    ct.append(tr);
  });
  app.append(ct);
</script>
```

- [ ] **Step 2: Verify it renders with sample data**

Substitute a small sample for `{{DATA_JSON}}` and open in a browser (or eyeball the structure):

```bash
python3 scripts/audit.py cli/cli --weeks 2 --months 2 > /tmp/audit.json
python3 - <<'PY'
import pathlib, json
tpl = pathlib.Path("templates/dashboard.html").read_text()
data = pathlib.Path("/tmp/audit.json").read_text()
out = tpl.replace("{{DATA_JSON}}", data)
pathlib.Path("/tmp/dashboard.html").write_text(out)
print("wrote /tmp/dashboard.html")
PY
open /tmp/dashboard.html
```

Expected: a dashboard with stat cards, weekly + monthly tables, and a contributor list — no console errors, no broken layout.

- [ ] **Step 3: Commit**

```bash
git add templates/dashboard.html
git commit -m "feat: self-contained HTML dashboard template"
```

---

### Task 5: SKILL.md + install + end-to-end verification

**Files:**
- Create: `SKILL.md`
- Create: `README.md` (short usage + install note)

**Interfaces:**
- Consumes: `scripts/audit.py` (Task 3), `templates/dashboard.html` (Task 4).
- Produces: the installable skill. No code interface; this wires everything for Claude to invoke.

- [ ] **Step 1: Write SKILL.md**

```markdown
---
name: github-repo-audit
description: Audit a single GitHub repository's pull-request activity. Use when the user asks to audit a repo, wants PR stats (opened/closed/merged) weekly or monthly, asks who is contributing or how many developers are active, or wants hotfix or revert PR counts for an owner/name repo. Produces an HTML dashboard.
---

# GitHub Repo Audit

Generate a PR-activity dashboard for one GitHub repository.

## Prerequisites

- The `gh` CLI must be installed and authenticated (`gh auth status`). If it is
  not, tell the user and stop — do not estimate or fabricate any numbers.

## Steps

1. **Get the repo.** You need an `owner/name` (e.g. `cli/cli`). If the user did
   not give one, ask.

2. **Run the audit script** from the skill directory:

   `python3 scripts/audit.py <owner/name>`

   Optional flags: `--weeks N` (default 4), `--months N` (default 3),
   `--limit N` (default 500).

3. **On error:** if the script exits non-zero, show the user its stderr verbatim
   (it is usually an auth or repo-access problem). Do not proceed to render.

4. **Render the dashboard.** Read `templates/dashboard.html`, replace the single
   token `{{DATA_JSON}}` with the exact JSON the script printed, and publish the
   result as an HTML Artifact titled `Repo Audit — <owner/name>`.

5. **Summarize** in one or two lines: total PRs opened/merged in the window,
   number of contributors, and hotfix/revert counts — then point to the dashboard.

## Notes

- All counting is done by the script; never re-tally numbers yourself.
- `opened`/`closed`/`merged` are each bucketed by their own timestamp, so a PR
  opened in one week and merged in another contributes to different buckets.
```

- [ ] **Step 2: Write README.md**

```markdown
# github-repo-audit

A Claude Code skill that audits one GitHub repo's PR activity and renders an
HTML dashboard.

## Install

Copy this folder into your Claude skills directory:

    cp -r github-repo-audit ~/.claude/skills/github-repo-audit

Then invoke in Claude Code: "audit the cli/cli repo".

## Requirements

- `gh` CLI, authenticated (`gh auth status`)
- Python 3 (standard library only)

## Run the script directly

    python3 scripts/audit.py owner/name --weeks 4 --months 3

Prints a JSON report to stdout.

## Test

    python3 -m unittest discover -s tests -v
```

- [ ] **Step 3: Run the full test suite (verification gate)**

Run: `python3 -m unittest discover -s tests -v`
Expected: ALL tests PASS. Record the count in the verification report.

- [ ] **Step 4: End-to-end dry run**

Run: `python3 scripts/audit.py cli/cli | python3 -c "import sys,json; d=json.load(sys.stdin); print('OK', d['repo'], d['totals'])"`
Expected: prints `OK cli/cli {...}` with sane numbers.

- [ ] **Step 5: Install and live-invoke**

```bash
cp -r . ~/.claude/skills/github-repo-audit
```

Then in a Claude Code session, ask "audit the cli/cli repo" and confirm the
skill triggers, the script runs, and an HTML Artifact appears.

- [ ] **Step 6: Commit**

```bash
git add SKILL.md README.md
git commit -m "feat: SKILL.md, README, and install instructions"
```

---

## Self-Review

**Spec coverage:**
- One repo per run → Task 3 CLI takes one `owner/name`. ✓
- Weekly + monthly rollups → Task 2 `bucket_by_week`/`bucket_by_month`. ✓
- PRs opened/closed/merged → Task 2 buckets + totals. ✓
- Contributors + per-author count → Task 2 `contributors`. ✓
- Hotfix (`hotfix/` branch) → Task 1 `classify`. ✓
- Revert (multi-signal) → Task 1 `classify`. ✓
- HTML artifact output → Task 4 template + Task 5 SKILL.md render step. ✓
- Script computes / Claude renders (Approach A) → Tasks 1-3 (script) vs Task 5 (render). ✓
- gh-failure surfaces, no fabricated numbers → Task 3 `main` + Task 5 step 3. ✓
- Empty repo → zero report → Task 2 `test_empty_input`. ✓
- stdlib-only incl. tests → `unittest` throughout. ✓
- `now` injected, never called in pure fns → `build_report`/`main` take `now`. ✓

**Placeholder scan:** No "TBD"/"add error handling"/"similar to Task N" — every code step has complete code. The `{{DATA_JSON}}` token in the template is an intentional runtime substitution point, documented in Task 5, not a plan placeholder. ✓

**Type consistency:** `classify` returns `{is_hotfix, is_revert}` (used in Task 2 totals + Task 1 tests). `build_report` signature `(prs, repo, now, weeks=4, months=3)` matches its call in `main`. `fetch(repo, limit=...)` keyword matches the injected fakes in Task 3 tests. Report keys (`repo`, `window.since`, `weekly`, `monthly`, `contributors`, `totals`) match the template's `DATA.*` reads. ✓
