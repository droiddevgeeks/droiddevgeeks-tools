# PR Velocity Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add time-to-merge and first-review-latency metrics (p50 + p90) to the github-audit plugin's single-repo and portfolio modes.

**Architecture:** New pure functions in `audit.py` compute per-PR durations from data already returned by `gh pr list` (the `reviews` field rides inline — no new API calls). `build_report` attaches a `velocity` block; `build_portfolio` pools raw per-PR durations across repos for an honest org-wide percentile. Two HTML templates gain a velocity panel / two table columns.

**Tech Stack:** Python 3 stdlib only (no third-party deps), `unittest`, `gh` CLI (mocked in tests), vanilla-JS HTML templates.

## Global Constraints

- **Stdlib only.** No new Python dependencies. (`audit.py` docstring: "Stdlib only.")
- **Author mode is out of scope.** Do not touch `search_author_prs`, `build_author_report`, `main_author`, or `author.html`.
- **Known-bot set:** `coderabbitai`, `copilot`, `dependabot`, `github-actions`, plus any login ending in `[bot]` (case-insensitive).
- **Statistic:** median (p50) + p90 only. No mean. Reuse the existing `audit._percentile(sorted_vals, pct)` helper.
- **Durations:** calendar time, stored in **hours** (float). Template formats `<24h` → `"{n}h"`, else `"{n}d"` (rounded).
- **Review scope:** review stats are measured over **merged** PRs only, so `reviewed_count + no_review_count == merged_count` holds exactly.
- All file paths are under the repo root `/Users/kishankumarmaurya/Development/AI/droiddevgeeks-tools`. Edit the **repo source** (`skills/github-audit/...`), not the plugin cache.
- Run tests from the skill dir: `cd skills/github-audit && python3 -m pytest tests/ -q` (or `python3 -m unittest discover tests -v`).

---

### Task 1: Bot identification + fetch the `reviews` field

**Files:**
- Modify: `skills/github-audit/scripts/audit.py` (add `_is_bot`, extend `GH_FIELDS`)
- Test: `skills/github-audit/tests/test_audit.py`

**Interfaces:**
- Produces: `audit._is_bot(login: str | None) -> bool`; `KNOWN_BOTS: set[str]`; `GH_FIELDS` string now ends with `,reviews`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audit.py`:

```python
class IsBotTests(unittest.TestCase):
    def test_bracket_bot_suffix(self):
        self.assertTrue(audit._is_bot("dependabot[bot]"))
        self.assertTrue(audit._is_bot("Some-App[bot]"))

    def test_known_bots(self):
        for login in ("coderabbitai", "copilot", "dependabot", "github-actions"):
            self.assertTrue(audit._is_bot(login), login)

    def test_case_insensitive(self):
        self.assertTrue(audit._is_bot("CodeRabbitAI"))

    def test_human_is_not_bot(self):
        self.assertFalse(audit._is_bot("kishan-cashfree"))

    def test_none_and_empty_safe(self):
        self.assertFalse(audit._is_bot(None))
        self.assertFalse(audit._is_bot(""))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/github-audit && python3 -m unittest tests.test_audit.IsBotTests -v`
Expected: FAIL — `AttributeError: module 'scripts.audit' has no attribute '_is_bot'`

- [ ] **Step 3: Write minimal implementation**

In `audit.py`, near the other module constants (after the `REVERT_*` constants around line 12):

```python
KNOWN_BOTS = {"coderabbitai", "copilot", "dependabot", "github-actions"}


def _is_bot(login):
    """True for known review bots and any login ending in '[bot]'."""
    l = (login or "").lower()
    return l.endswith("[bot]") or l in KNOWN_BOTS
```

Then extend `GH_FIELDS` (currently ends `...changedFiles"`) to also fetch reviews:

```python
GH_FIELDS = ("number,title,author,createdAt,closedAt,mergedAt,updatedAt,state,"
             "headRefName,labels,additions,deletions,changedFiles,reviews")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/github-audit && python3 -m unittest tests.test_audit.IsBotTests -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/github-audit/scripts/audit.py skills/github-audit/tests/test_audit.py
git commit -m "feat(audit): add _is_bot and fetch PR reviews field"
```

---

### Task 2: Per-PR duration helpers

**Files:**
- Modify: `skills/github-audit/scripts/audit.py` (add `_merge_hours`, `_first_review_hours`)
- Test: `skills/github-audit/tests/test_audit.py`

**Interfaces:**
- Consumes: `audit.parse_dt`, `audit._is_bot`.
- Produces:
  - `audit._merge_hours(pr: dict) -> float | None` — calendar hours `createdAt`→`mergedAt`, `None` if unmerged.
  - `audit._first_review_hours(pr: dict) -> float | None` — calendar hours `createdAt`→earliest non-author, non-bot `reviews[].submittedAt`; `None` if no qualifying human review.
- PR shape for reviews: `pr["author"] = {"login": "..."}`, `pr["reviews"] = [{"author": {"login": "..."}, "submittedAt": "ISO", "state": "..."}]`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audit.py`:

```python
def _rpr(*, created=None, merged=None, author="alice", reviews=None):
    """A PR shaped for velocity: author login + inline reviews."""
    return {
        "createdAt": created,
        "mergedAt": merged,
        "author": {"login": author},
        "reviews": reviews or [],
    }


def _rev(login, submitted):
    return {"author": {"login": login}, "submittedAt": submitted, "state": "APPROVED"}


class MergeHoursTests(unittest.TestCase):
    def test_hours_delta(self):
        pr = _rpr(created="2026-06-01T00:00:00Z", merged="2026-06-01T12:00:00Z")
        self.assertEqual(audit._merge_hours(pr), 12.0)

    def test_unmerged_is_none(self):
        self.assertIsNone(audit._merge_hours(_rpr(created="2026-06-01T00:00:00Z", merged=None)))

    def test_missing_created_is_none(self):
        self.assertIsNone(audit._merge_hours(_rpr(created=None, merged="2026-06-01T00:00:00Z")))


class FirstReviewHoursTests(unittest.TestCase):
    def test_earliest_human_review(self):
        pr = _rpr(created="2026-06-01T00:00:00Z", merged="2026-06-02T00:00:00Z", author="alice",
                  reviews=[_rev("bob", "2026-06-01T06:00:00Z"),
                           _rev("carol", "2026-06-01T03:00:00Z")])
        self.assertEqual(audit._first_review_hours(pr), 3.0)

    def test_excludes_self_review(self):
        pr = _rpr(created="2026-06-01T00:00:00Z", merged="2026-06-02T00:00:00Z", author="alice",
                  reviews=[_rev("alice", "2026-06-01T01:00:00Z"),
                           _rev("bob", "2026-06-01T05:00:00Z")])
        self.assertEqual(audit._first_review_hours(pr), 5.0)

    def test_excludes_bot_review(self):
        pr = _rpr(created="2026-06-01T00:00:00Z", merged="2026-06-02T00:00:00Z", author="alice",
                  reviews=[_rev("coderabbitai", "2026-06-01T00:05:00Z"),
                           _rev("dependabot[bot]", "2026-06-01T00:10:00Z"),
                           _rev("bob", "2026-06-01T04:00:00Z")])
        self.assertEqual(audit._first_review_hours(pr), 4.0)

    def test_no_human_review_is_none(self):
        pr = _rpr(created="2026-06-01T00:00:00Z", merged="2026-06-02T00:00:00Z", author="alice",
                  reviews=[_rev("alice", "2026-06-01T01:00:00Z"),
                           _rev("copilot", "2026-06-01T00:05:00Z")])
        self.assertIsNone(audit._first_review_hours(pr))

    def test_empty_reviews_is_none(self):
        pr = _rpr(created="2026-06-01T00:00:00Z", merged="2026-06-02T00:00:00Z", reviews=[])
        self.assertIsNone(audit._first_review_hours(pr))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/github-audit && python3 -m unittest tests.test_audit.MergeHoursTests tests.test_audit.FirstReviewHoursTests -v`
Expected: FAIL — `AttributeError: ... '_merge_hours'`

- [ ] **Step 3: Write minimal implementation**

In `audit.py`, after `_first_review_hours`'s sibling helpers (place near `_lines` / `_percentile`, before `size_distribution`):

```python
def _merge_hours(pr):
    """Calendar hours from PR creation to merge; None if never merged."""
    created = parse_dt(pr.get("createdAt"))
    merged = parse_dt(pr.get("mergedAt"))
    if not (created and merged):
        return None
    return (merged - created).total_seconds() / 3600.0


def _first_review_hours(pr):
    """Calendar hours to the earliest non-author, non-bot review; None if none."""
    created = parse_dt(pr.get("createdAt"))
    if not created:
        return None
    author = (pr.get("author") or {}).get("login")
    times = []
    for r in (pr.get("reviews") or []):
        login = (r.get("author") or {}).get("login")
        if not login or _is_bot(login) or login == author:
            continue
        t = parse_dt(r.get("submittedAt"))
        if t:
            times.append(t)
    if not times:
        return None
    return (min(times) - created).total_seconds() / 3600.0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/github-audit && python3 -m unittest tests.test_audit.MergeHoursTests tests.test_audit.FirstReviewHoursTests -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/github-audit/scripts/audit.py skills/github-audit/tests/test_audit.py
git commit -m "feat(audit): add per-PR merge and first-review duration helpers"
```

---

### Task 3: `velocity()` aggregator

**Files:**
- Modify: `skills/github-audit/scripts/audit.py` (add `velocity`)
- Test: `skills/github-audit/tests/test_audit.py`

**Interfaces:**
- Consumes: `_merge_hours`, `_first_review_hours`, `_percentile`.
- Produces: `audit.velocity(prs: list[dict]) -> dict` with keys:
  `merge_p50, merge_p90, review_p50, review_p90` (floats),
  `merged_count, reviewed_count, no_review_count` (ints),
  `_merge_hours, _review_hours` (list[float], internal pooling aids).
- Invariant: `reviewed_count + no_review_count == merged_count`. Review stats are over merged PRs only.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audit.py` (reuses `_rpr` / `_rev` from Task 2):

```python
class VelocityTests(unittest.TestCase):
    def _fixture(self):
        # 3 merged PRs: merge times 2h, 10h, 30h; reviews: 1h, none(bot only), 5h
        return [
            _rpr(created="2026-06-01T00:00:00Z", merged="2026-06-01T02:00:00Z",
                 author="alice", reviews=[_rev("bob", "2026-06-01T01:00:00Z")]),
            _rpr(created="2026-06-01T00:00:00Z", merged="2026-06-01T10:00:00Z",
                 author="alice", reviews=[_rev("copilot", "2026-06-01T00:05:00Z")]),
            _rpr(created="2026-06-01T00:00:00Z", merged="2026-06-02T06:00:00Z",
                 author="alice", reviews=[_rev("carol", "2026-06-01T05:00:00Z")]),
            _rpr(created="2026-06-01T00:00:00Z", merged=None, author="alice"),  # open, ignored
        ]

    def test_counts(self):
        v = audit.velocity(self._fixture())
        self.assertEqual(v["merged_count"], 3)
        self.assertEqual(v["reviewed_count"], 2)
        self.assertEqual(v["no_review_count"], 1)
        self.assertEqual(v["reviewed_count"] + v["no_review_count"], v["merged_count"])

    def test_merge_percentiles(self):
        v = audit.velocity(self._fixture())
        # sorted merge hours: [2, 10, 30]; nearest-rank p50 -> 10, p90 -> 30
        self.assertEqual(v["merge_p50"], 10.0)
        self.assertEqual(v["merge_p90"], 30.0)

    def test_review_percentiles(self):
        v = audit.velocity(self._fixture())
        # sorted review hours: [1, 5]; p50 -> 1, p90 -> 5
        self.assertEqual(v["review_p50"], 1.0)
        self.assertEqual(v["review_p90"], 5.0)

    def test_raw_lists_present(self):
        v = audit.velocity(self._fixture())
        self.assertEqual(sorted(v["_merge_hours"]), [2.0, 10.0, 30.0])
        self.assertEqual(sorted(v["_review_hours"]), [1.0, 5.0])

    def test_empty_is_safe(self):
        v = audit.velocity([])
        self.assertEqual(v["merged_count"], 0)
        self.assertEqual(v["merge_p50"], 0)
        self.assertEqual(v["no_review_count"], 0)
        self.assertEqual(v["_merge_hours"], [])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/github-audit && python3 -m unittest tests.test_audit.VelocityTests -v`
Expected: FAIL — `AttributeError: ... 'velocity'`

- [ ] **Step 3: Write minimal implementation**

In `audit.py`, after `_first_review_hours`:

```python
def velocity(prs):
    """Aggregate merge and first-review durations over merged PRs.

    Review stats are scoped to merged PRs so that
    reviewed_count + no_review_count == merged_count.
    """
    merge_hours, review_hours = [], []
    no_review = 0
    for pr in prs:
        mh = _merge_hours(pr)
        if mh is None:
            continue
        merge_hours.append(mh)
        rh = _first_review_hours(pr)
        if rh is None:
            no_review += 1
        else:
            review_hours.append(rh)
    ms, rs = sorted(merge_hours), sorted(review_hours)
    return {
        "merge_p50": _percentile(ms, 0.5),
        "merge_p90": _percentile(ms, 0.9),
        "review_p50": _percentile(rs, 0.5),
        "review_p90": _percentile(rs, 0.9),
        "merged_count": len(merge_hours),
        "reviewed_count": len(review_hours),
        "no_review_count": no_review,
        "_merge_hours": merge_hours,
        "_review_hours": review_hours,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/github-audit && python3 -m unittest tests.test_audit.VelocityTests -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add skills/github-audit/scripts/audit.py skills/github-audit/tests/test_audit.py
git commit -m "feat(audit): add velocity aggregator (p50/p90 merge + review)"
```

---

### Task 4: Wire velocity into `build_report`

**Files:**
- Modify: `skills/github-audit/scripts/audit.py` (`build_report`)
- Test: `skills/github-audit/tests/test_audit.py`

**Interfaces:**
- Consumes: `velocity`, the existing `in_window` list inside `build_report`.
- Produces: `build_report(...)` output now contains a `"velocity"` key (the `velocity()` dict).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_audit.py` inside `ReportIntegrationTests` (or as a new method):

```python
    def test_report_includes_velocity(self):
        prs = [
            {"number": 1, "state": "MERGED",
             "createdAt": "2026-06-10T00:00:00Z", "mergedAt": "2026-06-10T04:00:00Z",
             "updatedAt": "2026-06-10T04:00:00Z", "author": {"login": "alice"},
             "reviews": [{"author": {"login": "bob"}, "submittedAt": "2026-06-10T01:00:00Z"}],
             "additions": 10, "deletions": 0, "changedFiles": 1},
        ]
        report = audit.build_report(prs, "owner/name", NOW)
        self.assertIn("velocity", report)
        self.assertEqual(report["velocity"]["merged_count"], 1)
        self.assertEqual(report["velocity"]["merge_p50"], 4.0)
        self.assertEqual(report["velocity"]["review_p50"], 1.0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/github-audit && python3 -m unittest tests.test_audit.ReportIntegrationTests.test_report_includes_velocity -v`
Expected: FAIL — `KeyError: 'velocity'`

- [ ] **Step 3: Write minimal implementation**

In `build_report`, compute velocity from `in_window` (right after `size_stats = size_distribution(in_window)`):

```python
    velocity_stats = velocity(in_window)
```

Then add it to the returned dict (after the `"size": size_stats,` line):

```python
        "size": size_stats,
        "velocity": velocity_stats,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/github-audit && python3 -m unittest tests.test_audit.ReportIntegrationTests -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add skills/github-audit/scripts/audit.py skills/github-audit/tests/test_audit.py
git commit -m "feat(audit): attach velocity block to single-repo report"
```

---

### Task 5: Pool velocity across the portfolio

**Files:**
- Modify: `skills/github-audit/scripts/audit.py` (`build_portfolio`)
- Test: `skills/github-audit/tests/test_audit.py`

**Interfaces:**
- Consumes: each entry's `report["velocity"]` (including `_merge_hours` / `_review_hours`).
- Produces:
  - Per-repo dicts in `portfolio["repos"]` gain: `merge_p50, merge_p90, review_p50, review_p90, reviewed_count, no_review_count, merged_count`.
  - `portfolio["totals"]` gains org-wide pooled `merge_p50, merge_p90, review_p50, review_p90` (percentile over the **pooled raw durations**, not median-of-medians).
  - Pooled raw lists are **not** present in the output.

- [ ] **Step 1: Write the failing test**

The existing `_report` test helper does not emit a `velocity` block. Add a velocity-aware helper and a test class to `tests/test_audit.py`:

```python
def _report_v(repo, *, merge_hours=(), review_hours=(), no_review=0, opened=0, merged=0):
    r = _report(repo, opened=opened, merged=merged)
    ms, rs = sorted(merge_hours), sorted(review_hours)
    r["velocity"] = {
        "merge_p50": audit._percentile(ms, 0.5), "merge_p90": audit._percentile(ms, 0.9),
        "review_p50": audit._percentile(rs, 0.5), "review_p90": audit._percentile(rs, 0.9),
        "merged_count": len(ms), "reviewed_count": len(rs), "no_review_count": no_review,
        "_merge_hours": list(merge_hours), "_review_hours": list(review_hours),
    }
    return r


class PortfolioVelocityTests(unittest.TestCase):
    def test_pooled_p50_is_not_median_of_medians(self):
        # repoA merge hours: [1, 1, 1, 1, 100]  -> own p50 = 1
        # repoB merge hours: [50, 50, 50]        -> own p50 = 50
        # median-of-medians would be ~25.5; pooled sorted:
        #   [1,1,1,1,50,50,50,100] -> nearest-rank p50 (rank ceil(.5*8)=4) = 1
        entries = [
            _entry(_report_v("o/a", merge_hours=[1, 1, 1, 1, 100], merged=5)),
            _entry(_report_v("o/b", merge_hours=[50, 50, 50], merged=3)),
        ]
        p = audit.build_portfolio("o", entries, NOW, 4, 3)
        self.assertEqual(p["totals"]["merge_p50"], 1)
        # sanity: per-repo medians differ from the pooled value
        a = next(r for r in p["repos"] if r["repo"] == "o/a")
        self.assertEqual(a["merge_p50"], 1)

    def test_per_repo_velocity_carried(self):
        entries = [_entry(_report_v("o/a", merge_hours=[2, 4, 6],
                                    review_hours=[1, 3], no_review=1, merged=3))]
        p = audit.build_portfolio("o", entries, NOW, 4, 3)
        a = next(r for r in p["repos"] if r["repo"] == "o/a")
        self.assertEqual(a["merge_p50"], 4)
        self.assertEqual(a["review_p50"], 3)
        self.assertEqual(a["reviewed_count"], 2)
        self.assertEqual(a["no_review_count"], 1)

    def test_pooled_lists_not_leaked(self):
        entries = [_entry(_report_v("o/a", merge_hours=[2, 4], merged=2))]
        p = audit.build_portfolio("o", entries, NOW, 4, 3)
        self.assertNotIn("_merge_hours", p["totals"])
        for r in p["repos"]:
            self.assertNotIn("_merge_hours", r)

    def test_empty_velocity_safe(self):
        # entries with no velocity block (back-compat) must not crash
        p = audit.build_portfolio("o", [_entry(_report("o/x"))], NOW, 4, 3)
        self.assertEqual(p["totals"]["merge_p50"], 0)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/github-audit && python3 -m unittest tests.test_audit.PortfolioVelocityTests -v`
Expected: FAIL — `KeyError: 'merge_p50'` in totals (and per-repo).

- [ ] **Step 3: Write minimal implementation**

In `build_portfolio`, inside the `for e in entries:` loop, read the velocity block and pool it. Add near the top of the loop body (alongside `S = rep.get("size") or {}`):

```python
        V = rep.get("velocity") or {}
        pooled_merge.extend(V.get("_merge_hours", []))
        pooled_review.extend(V.get("_review_hours", []))
```

Initialize the pools before the loop (next to `agg = {...}`):

```python
    pooled_merge, pooled_review = [], []
```

In the per-repo `repos.append({...})` dict, add velocity fields (after `"p90_lines": S.get("p90_lines", 0),`):

```python
            "merge_p50": V.get("merge_p50", 0),
            "merge_p90": V.get("merge_p90", 0),
            "review_p50": V.get("review_p50", 0),
            "review_p90": V.get("review_p90", 0),
            "merged_count": V.get("merged_count", 0),
            "reviewed_count": V.get("reviewed_count", 0),
            "no_review_count": V.get("no_review_count", 0),
```

After the loop, compute pooled org-wide percentiles and fold into `totals`. Find the `totals = {...}` dict and add these keys (pooled lists are used here and never stored):

```python
    pm, pr_ = sorted(pooled_merge), sorted(pooled_review)
    totals = {
        "repos": len(repos),
        "active_repos": sum(1 for r in repos if r["opened"] > 0),
        "contributors": len(org_contrib),
        "merge_p50": _percentile(pm, 0.5),
        "merge_p90": _percentile(pm, 0.9),
        "review_p50": _percentile(pr_, 0.5),
        "review_p90": _percentile(pr_, 0.9),
        **agg,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/github-audit && python3 -m unittest tests.test_audit.PortfolioVelocityTests -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `cd skills/github-audit && python3 -m unittest discover tests -v`
Expected: PASS — all prior tests still green.

- [ ] **Step 6: Commit**

```bash
git add skills/github-audit/scripts/audit.py skills/github-audit/tests/test_audit.py
git commit -m "feat(audit): pool per-repo durations for org-wide velocity"
```

---

### Task 6: Render the Velocity panel in `dashboard.html`

**Files:**
- Modify: `skills/github-audit/templates/dashboard.html`

**Interfaces:**
- Consumes: `DATA.velocity` (`merge_p50/p90`, `review_p50/p90`, `merged_count`, `reviewed_count`, `no_review_count`).
- Reuses existing `el`, `fmt`, and the panel/chip markup pattern used by the `DATA.size` block.

- [ ] **Step 1: Add a duration formatter near the other formatters**

After the `const fmt = ...` line (around line 149):

```js
  const fmtDur = h => (h == null ? "—" : (h < 24 ? Math.round(h) + "h" : Math.round(h / 24) + "d"));
```

- [ ] **Step 2: Add the Velocity panel**

Immediately **after** the closing of the `if (DATA.size) { ... grid.append(panel); }` block and **before** `if (grid.childElementCount) app.append(grid);` (line ~322), insert:

```js
  if (DATA.velocity && DATA.velocity.merged_count > 0) {
    const V = DATA.velocity;
    const panel = el("div", { className: "panel" });
    panel.append(el("h2", { textContent: "Velocity" }));
    const chips = el("div", { className: "chiprow" });
    const chip = (txt, val, cls) => {
      const c = el("div", { className: "chip" + (cls ? " " + cls : "") });
      c.append(el("b", { textContent: val })); c.append(document.createTextNode(" " + txt));
      return c;
    };
    chips.append(chip("merge p50", fmtDur(V.merge_p50)));
    chips.append(chip("merge p90", fmtDur(V.merge_p90), V.merge_p90 >= 168 ? "warn" : ""));
    chips.append(chip("review p50", V.reviewed_count ? fmtDur(V.review_p50) : "—"));
    chips.append(chip("review p90", V.reviewed_count ? fmtDur(V.review_p90) : "—",
      V.reviewed_count && V.review_p90 >= 72 ? "warn" : ""));
    panel.append(chips);
    panel.append(el("p", { className: "hint",
      textContent: `${V.no_review_count} of ${V.merged_count} merged with no human review.` }));
    grid.append(panel);
  }
```

- [ ] **Step 3: Verify the render against real data**

Regenerate a dashboard from a live repo and confirm the panel appears with sane numbers:

```bash
cd skills/github-audit
python3 scripts/audit.py cashfree/flutter-cashfree-pg-sdk > /tmp/vel.json
python3 - <<'PY'
import pathlib, json
data = pathlib.Path("/tmp/vel.json").read_text().strip()
v = json.loads(data)["velocity"]
print("velocity block:", v["merged_count"], "merged,", v["no_review_count"], "no-review,",
      "p50", v["merge_p50"], "p90", v["merge_p90"])
out = pathlib.Path("templates/dashboard.html").read_text().replace("{{DATA_JSON}}", data)
assert "{{DATA_JSON}}" not in out
pathlib.Path("/tmp/vel-dash.html").write_text(out)
print("wrote /tmp/vel-dash.html")
PY
/usr/bin/open /tmp/vel-dash.html
```

Expected: a "Velocity" panel renders alongside PR Size / Backlog with merge p50/p90, review p50/p90 chips and the no-review footnote. No console errors.

- [ ] **Step 4: Commit**

```bash
git add skills/github-audit/templates/dashboard.html
git commit -m "feat(dashboard): add Velocity panel (merge + review p50/p90)"
```

---

### Task 7: Add velocity columns to `portfolio.html`

**Files:**
- Modify: `skills/github-audit/templates/portfolio.html`

**Interfaces:**
- Consumes: per-repo `r.merge_p50/p90`, `r.review_p50/p90`, `r.merged_count`, `r.reviewed_count`; and `DATA.totals.merge_p50`, `DATA.totals.review_p50`.
- Reuses existing `el`, `fmt`, `addSignal`, and the table-building code.

- [ ] **Step 1: Add a duration formatter near `fmt`**

After the `const fmt = ...` definition (around line 117 region in portfolio.html — locate the existing `const fmt =` line):

```js
  const fmtDur = h => (h == null ? "—" : (h < 24 ? Math.round(h) + "h" : Math.round(h / 24) + "d"));
```

- [ ] **Step 2: Add org-wide velocity signals**

After the existing `addSignal("stale open PRs", ...)` line (~line 140), add:

```js
  if (T.merge_p50) addSignal("merge p50", fmtDur(T.merge_p50));
  if (T.review_p50) addSignal("review p50", fmtDur(T.review_p50));
```

- [ ] **Step 3: Add the two table columns to the header**

Replace the header column array (currently):

```js
  ["Repository", "Opened", "Merged", "Closed", "Contrib", "Open", "Stale", "Median", "Stars"]
    .forEach(h => htr.append(el("th", { textContent: h })));
```

with (insert `"Merge p50"` and `"Review p50"` before `"Stars"`):

```js
  ["Repository", "Opened", "Merged", "Closed", "Contrib", "Open", "Stale", "Median", "Merge p50", "Review p50", "Stars"]
    .forEach(h => htr.append(el("th", { textContent: h })));
```

- [ ] **Step 4: Add the two cells to each row**

In the `DATA.repos.forEach(r => { ... })` body, the cells are appended in header order. **Before** the Stars cell (`tr.append(el("td", { textContent: fmt(r.stars) }));`), insert:

```js
    const mc = el("td", { textContent: r.merged_count ? fmtDur(r.merge_p50) : "—" });
    if (r.merge_p90) mc.title = "p90 " + fmtDur(r.merge_p90);
    tr.append(mc);
    const rvc = el("td", { textContent: r.reviewed_count ? fmtDur(r.review_p50) : "—" });
    if (r.reviewed_count && r.review_p90) rvc.title = "p90 " + fmtDur(r.review_p90);
    tr.append(rvc);
```

- [ ] **Step 5: Verify the render against real data**

```bash
cd skills/github-audit
python3 scripts/audit_user.py cashfree > /tmp/port.json 2>/dev/null
python3 - <<'PY'
import pathlib, json
data = pathlib.Path("/tmp/port.json").read_text().strip()
t = json.loads(data)["totals"]
print("org merge_p50:", t.get("merge_p50"), "review_p50:", t.get("review_p50"))
out = pathlib.Path("templates/portfolio.html").read_text().replace("{{DATA_JSON}}", data)
assert "{{DATA_JSON}}" not in out
pathlib.Path("/tmp/vel-port.html").write_text(out)
print("wrote /tmp/vel-port.html")
PY
/usr/bin/open /tmp/vel-port.html
```

Expected: the per-repo table shows `Merge p50` and `Review p50` columns (with p90 on hover), the summary strip shows org-wide merge/review p50, and column count matches header count. No console errors.

- [ ] **Step 6: Commit**

```bash
git add skills/github-audit/templates/portfolio.html
git commit -m "feat(portfolio): add merge/review p50 columns and org-wide signals"
```

---

### Task 8: Update SKILL.md docs + final verification

**Files:**
- Modify: `skills/github-audit/SKILL.md` (note the new velocity metrics in single-repo + portfolio summaries)
- Modify: `README.md` if it enumerates per-mode metrics

**Interfaces:** none (docs only).

- [ ] **Step 1: Check what the docs currently claim**

Run: `grep -ni "backlog\|hotfix\|size\|velocity\|summariz" skills/github-audit/SKILL.md README.md`
Read the matching lines to find where per-mode metrics are described.

- [ ] **Step 2: Update the summaries**

In `SKILL.md` step 5 (Summarize), add velocity to the single-repo and portfolio summary guidance, e.g. append to the single-repo line: "…and merge/first-review p50." and to portfolio: "…plus org-wide merge p50." Keep wording consistent with the existing terse style. Make the analogous edit in `README.md` only if it lists metrics per mode.

- [ ] **Step 3: Run the full test suite one final time**

Run: `cd skills/github-audit && python3 -m unittest discover tests -v`
Expected: PASS — entire suite green.

- [ ] **Step 4: Commit**

```bash
git add skills/github-audit/SKILL.md README.md
git commit -m "docs: document PR velocity metrics in skill and readme"
```

---

## Self-Review

**Spec coverage:**
- Statistic p50+p90, no mean → Tasks 3, 6, 7. ✓
- Calendar time, hours, `<24h`/`else d` format → `fmtDur` in Tasks 6 & 7; durations in hours in Task 2. ✓
- `reviews` field inline, no extra API calls → Task 1 (`GH_FIELDS`). ✓
- Bot + self-review exclusion → Tasks 1, 2. ✓
- No-review PRs excluded from stat, count surfaced → Task 3 (`no_review_count`), Task 6 (footnote). ✓
- Author mode untouched → not referenced in any task; Global Constraints. ✓
- Honest portfolio pooling (not median-of-medians) → Task 5, with a test that proves it. ✓
- dashboard Velocity panel → Task 6. ✓
- portfolio two columns + p90 tooltip + org-wide summary → Task 7. ✓
- Edge cases (zero-merged → `—`, bot-only → no_review, missing fields) → Tasks 2/3 tests; Task 6/7 `—` guards. ✓
- Test list items 1–6 from spec → Tasks 1–5. ✓

**Placeholder scan:** No TBD/TODO; every code step shows complete code. ✓

**Type consistency:** `_is_bot`, `_merge_hours`, `_first_review_hours`, `velocity`, and the `velocity` dict keys (`merge_p50/p90`, `review_p50/p90`, `merged_count`, `reviewed_count`, `no_review_count`, `_merge_hours`, `_review_hours`) are used identically across Tasks 2–7. Per-repo portfolio keys match between Task 5 producer and Task 7 consumer. ✓
