# GitHub Repo Audit — Skill Design

**Date:** 2026-06-26
**Status:** Approved (design phase)
**Author:** kishan-cashfree

## Purpose

A Claude Code skill that produces a health/activity audit for a single GitHub
repository. Given one repo, it reports pull-request throughput and contributor
activity over recent time windows, plus counts of hotfix and revert PRs. The
output is a self-contained HTML dashboard artifact.

This is v1. The skill is expected to grow (more metrics, more repos) over time,
so the design favors a clean script/render boundary that new metrics can slot
into.

## Scope (v1)

- **Unit of analysis:** one repo per run. User passes the repo as
  `owner/name` (e.g. `cashfree/payments-sdk`).
- **Time window:** both weekly and monthly rollups in every run.
  - Weekly: the most recent 4 ISO weeks (Mon–Sun).
  - Monthly: the most recent 3 calendar months.
  - The fetch window is the max of those (≈90 days back) so both rollups have data.
- **Metrics:**
  - PRs opened per week / per month.
  - PRs closed per week / per month (closed = state `closed`, whether merged or not).
  - PRs merged per week / per month (subset of closed, `mergedAt` present).
  - Unique contributors (distinct PR authors) + per-author PR count.
  - Hotfix PR count.
  - Revert PR count.
- **Output:** one self-contained HTML dashboard, rendered as a Claude Artifact.

### Out of scope for v1 (explicitly deferred)

- Multiple repos / org-wide audit in a single run.
- Issue metrics, review latency, time-to-merge, CI/check data.
- Persisting history across runs / trend lines beyond the fetched window.
- Saved-file or terminal-only output modes.

## Classification rules

These are the rules that decide what each PR "is." They live in code and are
unit-tested, because wrong classification = wrong report.

- **Hotfix PR:** head branch name starts with `hotfix/` (case-insensitive).
- **Revert PR:** matches **any** of these signals (OR):
  - title starts with `Revert "` (GitHub's auto-generated revert title), OR
  - head branch starts with `revert/` or matches GitHub's `revert-<sha>-<branch>`
    auto pattern (i.e. branch name starts with `revert-`), OR
  - PR carries a label whose name, lowercased, equals `revert`.
- A PR can be counted in both hotfix and revert tallies if it matches both;
  these are independent counts, not mutually exclusive buckets.

The hotfix prefix and revert signals are defined as constants at the top of the
script so they are trivial to adjust as conventions change.

## Architecture (Approach A — script computes, Claude renders)

```
github-repo-audit/
├── SKILL.md              # frontmatter + orchestration instructions
├── scripts/
│   └── audit.py          # gh queries → classify → bucket → emit JSON to stdout
├── tests/
│   └── test_audit.py     # asserts classification + bucketing on fixture PRs
├── templates/
│   └── dashboard.html    # HTML/CSS shell with placeholder tokens
└── docs/superpowers/specs/2026-06-26-github-repo-audit-design.md
```

### Components

**`scripts/audit.py`** — the deterministic core.
- *What it does:* takes a repo arg, shells out to `gh pr list` to fetch recent
  PRs as JSON, classifies and buckets them, prints a single JSON object to stdout.
- *How it's used:* `python3 scripts/audit.py <owner/name> [--weeks 4] [--months 3]`.
- *Depends on:* `gh` CLI (already installed + authenticated), Python 3 stdlib
  only (no third-party packages — uses `subprocess`, `json`, `datetime`,
  `argparse`). Keeping it stdlib-only means no install step.
- *Fetch detail:* `gh pr list --repo <r> --state all --limit <N> --json
  number,title,author,createdAt,closedAt,mergedAt,state,headRefName,labels`.
  PRs are filtered to the fetch window in code by `createdAt`/`closedAt`.

**Pure functions inside the script** (the unit-tested surface):
- `classify(pr) -> {is_hotfix, is_revert}` — applies the rules above.
- `bucket_by_week(prs, now) -> [...]` and `bucket_by_month(prs, now) -> [...]`.
- `contributors(prs) -> [{login, count}]` sorted desc.
- `build_report(prs, now) -> dict` — assembles the final JSON shape.
These take plain data (already-parsed PR dicts) so tests never touch the network.

**`templates/dashboard.html`** — a static, self-contained HTML/CSS shell with
clearly marked placeholder tokens (e.g. `{{REPO}}`, `{{WEEKLY_ROWS}}`,
`{{DATA_JSON}}`). No external assets, no CDN — inline CSS and inline `<script>`
only, so it works as a Claude Artifact under a strict CSP. Charts, if any, are
rendered from inlined data with hand-rolled SVG/CSS bars rather than a chart
library.

**`SKILL.md`** — orchestration.
- Frontmatter `name: github-repo-audit` and a `description` written to trigger
  on phrasings like "audit my repo", "PR stats for <repo>", "who's contributing
  to <repo>", "hotfix/revert counts".
- Body instructs Claude to: (1) confirm/obtain the `owner/name`, (2) run
  `audit.py`, (3) if it errors, surface the error (auth, repo not found) rather
  than fabricating numbers, (4) load `dashboard.html`, fill placeholders from
  the JSON, (5) publish as an Artifact.

### Data flow

```
user invokes skill with owner/name
        │
        ▼
SKILL.md → python3 scripts/audit.py owner/name
        │
        ▼
gh pr list --json ...  ──►  classify + bucket (pure fns)  ──►  JSON to stdout
        │
        ▼
Claude reads JSON + templates/dashboard.html
        │
        ▼
fill placeholders → self-contained HTML → Artifact
```

### JSON contract (script stdout)

```json
{
  "repo": "owner/name",
  "generated_at": "2026-06-26T00:00:00Z",
  "window": { "weeks": 4, "months": 3, "since": "2026-03-28" },
  "weekly": [
    { "week_start": "2026-06-22", "opened": 12, "closed": 9, "merged": 8 }
  ],
  "monthly": [
    { "month": "2026-06", "opened": 40, "closed": 33, "merged": 30 }
  ],
  "contributors": [ { "login": "alice", "count": 14 } ],
  "totals": {
    "opened": 80, "closed": 70, "merged": 64,
    "hotfix": 5, "revert": 3, "contributors": 9
  }
}
```

## Error handling

- **`gh` not authenticated / not installed:** script exits non-zero with a clear
  stderr message; SKILL.md tells Claude to report it and stop, not guess numbers.
- **Repo not found / no access:** `gh` returns an error; surfaced verbatim.
- **Empty repo / zero PRs in window:** valid result — report renders with zeros,
  not an error.
- **Malformed/missing fields from `gh`:** script defends with `.get()` defaults;
  a PR missing `headRefName` simply can't match hotfix/revert.

## Testing strategy

Per project testing discipline — TDD, tests first, mock at the boundary.

- The network boundary is `gh`. Tests never call it; they feed fixture PR dicts
  (the same shape `gh --json` returns) straight into the pure functions.
- **Classification tests:** hotfix branch match (and case-insensitivity),
  each revert signal independently, a PR matching both, a plain PR matching
  neither, a PR missing `headRefName`.
- **Bucketing tests:** PRs landing in correct ISO week / calendar month; a PR
  on a week boundary; opened vs closed vs merged counted correctly; PR outside
  the window excluded.
- **Contributor tests:** distinct count, per-author tally, sort order, a PR with
  a null author (ghost user) handled.
- **Empty input:** zero PRs → all-zero report, no crash.
- Run with `python3 -m pytest tests/` (or stdlib `unittest` if we avoid the dep).

A passing test run is required before the skill is considered done; the
verification report will list which tests cover happy path / failure / boundary.

## Open questions / future iterations

- Add review-latency and time-to-merge metrics (needs `reviews`/timeline data).
- Multi-repo and org rollup (changes scope unit; revisit output layout).
- Configurable hotfix/revert rules via a small config block or flags.
- Optionally cache raw `gh` output to make re-renders free.
