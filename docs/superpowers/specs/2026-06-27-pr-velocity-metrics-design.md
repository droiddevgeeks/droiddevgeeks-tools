# PR Velocity Metrics — Design

**Date:** 2026-06-27
**Status:** Approved (design), pending implementation plan
**Scope:** Add PR velocity metrics — time-to-merge and first-review latency — to the
`github-audit` plugin's **single-repo** (`audit.py` / `dashboard.html`) and
**portfolio** (`audit_user.py` / `portfolio.html`) modes. **Author mode is explicitly
out of scope.**

## Motivation

The audit today counts PR *throughput* (opened / closed / merged, by week/month/repo/org)
plus backlog age, PR size, and hotfix/revert tagging. It answers "how much shipped" but
is silent on "how fast." Velocity — how long a PR takes to merge, and how long it waits
for its first human review — is the cycle-time signal engineering managers actually act
on. The data needed is nearly free: it rides along in the `gh pr list` call we already make.

## Decisions (settled during brainstorming)

| Question | Decision |
|---|---|
| Which statistic | **Median (p50) + p90.** Right-skewed durations; reuse existing `_percentile`. No mean. |
| Calendar vs business time | **Calendar time** (wall-clock, weekends included). Format: `<24h` → hours, else days. |
| What counts as a review | Formal `reviews[].submittedAt`, **excluding the PR author** and **excluding bots**. |
| No-review PRs | **Excluded** from the latency stat; the **count is reported** as its own signal. |
| Single-repo render | A "Velocity" panel: merge p50/p90, review p50/p90, no-review footnote. |
| Portfolio render | Two new sortable table columns (`merge p50`, `review p50`, p90 in tooltip) + org-wide median in summary strip. |
| Known-bot set | `coderabbitai`, `copilot`, `dependabot`, `github-actions`, plus the `[bot]`-suffix catch-all. |

## Data Source

Add `reviews` to `GH_FIELDS`. The field is returned inline by the existing
`gh pr list --json ...` call, so **no additional API requests** are made — the cost is a
marginally larger response payload. Each review record carries `author.login`, `state`,
and `submittedAt`.

Author mode continues to use `gh search prs`, which does **not** return review data or
reliable per-PR merge timing. It is therefore left unchanged; velocity is not added there.

## Components

All new logic lives in `audit.py` as pure, independently testable functions (stdlib only).

### `_is_bot(login) -> bool`
Returns `True` when `login` (case-insensitive) ends with `[bot]` or is in the known-bot
set `{coderabbitai, copilot, dependabot, github-actions}`. Single responsibility: bot
identification. No I/O.

### `_merge_hours(pr) -> float | None`
`(mergedAt - createdAt)` expressed in hours, using the existing `parse_dt`. Returns `None`
if the PR was never merged (no `mergedAt`).

### `_first_review_hours(pr) -> float | None`
Hours from `createdAt` to the **earliest** `reviews[].submittedAt` whose author is neither
the PR author nor a bot. Returns `None` if the PR received no qualifying human review.
Defensive against missing/empty `reviews` and missing `submittedAt`.

### `velocity(prs) -> dict`
Aggregates over the supplied (already window-filtered) PR list:

```
{
  "merge_p50": float, "merge_p90": float,        # over merged PRs
  "review_p50": float, "review_p90": float,      # over PRs with a human review
  "merged_count": int,
  "reviewed_count": int,
  "no_review_count": int,                        # merged PRs with no human review
  "_merge_hours": [float, ...],                  # internal: raw durations for pooling
  "_review_hours": [float, ...]                  # internal: raw durations for pooling
}
```

Percentiles computed via the existing `_percentile` helper. The `_`-prefixed lists exist
solely so the portfolio can compute an honest pooled org-wide percentile (see below); they
are small for a single repo and are **not** surfaced in portfolio output.

## Data Flow

### Single repo
`fetch_prs` (now requesting `reviews`) → `build_report` calls `velocity(in_window)` and
attaches the result under a new `"velocity"` key → `dashboard.html` renders the Velocity
panel. The raw `_merge_hours` / `_review_hours` lists remain in the single-repo JSON
(small, harmless).

### Portfolio
Each repo's `build_report` already produces a `velocity` block. `build_portfolio`:
- For the **per-repo table**: reads each repo's own `merge_p50` / `review_p50` (and p90).
- For the **org-wide summary**: **pools** the raw `_merge_hours` / `_review_hours` from
  every repo and computes the percentile over the combined set. Medianing per-repo medians
  is statistically invalid and is explicitly rejected. The pooled raw lists are consumed
  during aggregation and do **not** appear in the final portfolio JSON.

## Rendering

### `dashboard.html` — Velocity panel
A new panel alongside the existing size/backlog panels:
- Time to merge: `p50` and `p90` (formatted h/d).
- Time to first review: `p50` and `p90`.
- Footnote: `"{no_review_count} of {merged_count} merged with no human review"`.

### `portfolio.html`
- Two new columns in the per-repo table: `merge p50` and `review p50`. The p90 value is
  exposed via the cell's `title` (hover tooltip) to avoid column bloat. Columns are
  sortable like the existing ones.
- The org-wide pooled `merge_p50` **and** `review_p50` added to the top summary strip.

Formatting helper (template JS): `< 24h` → `"{n}h"`, otherwise `"{n}d"` (rounded).

## Error Handling / Edge Cases

- PR with no `reviews` array, empty array, or reviews missing `submittedAt` → treated as
  no human review (`_first_review_hours` returns `None`).
- All review authors are bots / the PR author → counts toward `no_review_count`.
- Repo with zero merged PRs in window → percentiles are `0` (consistent with existing
  `_percentile` empty behavior); panel/columns render `—` rather than `0h`.
- Missing `mergedAt` on an open PR → excluded from merge stats by `_merge_hours` returning
  `None`.

## Testing (TDD — RED first)

New cases in `tests/test_audit.py` (and `tests/test_report.py` where report-shaped):
1. `_is_bot`: `[bot]` suffix, each known-bot login, a normal human login (negative).
2. `_first_review_hours`: excludes self-review; excludes bot review; picks the earliest
   qualifying human review when several exist; returns `None` for no/empty/bot-only reviews.
3. `_merge_hours`: correct hour delta; `None` for unmerged.
4. `velocity`: p50/p90 over a known fixture; `merged_count` / `reviewed_count` /
   `no_review_count` correctness.
5. Portfolio pooling: a deliberately asymmetric two-repo fixture proving pooled p50
   differs from the median-of-medians.
6. All existing tests remain green.

## Out of Scope (YAGNI)

- Author-mode velocity (data source can't support it cheaply).
- Business-hours / timezone-aware durations.
- Mean / additional statistics beyond p50 + p90.
- Per-reviewer review-load metrics (separate future feature).
