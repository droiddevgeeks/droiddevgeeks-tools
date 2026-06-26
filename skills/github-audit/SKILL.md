---
name: github-audit
description: Audit GitHub pull-request activity three ways — a single repo (owner/name), a whole user/org's repos (portfolio), or one person's PRs across all repos (contributions). Use when the user asks to audit a repo, wants PR stats (opened/closed/merged) weekly or monthly, asks who is contributing or how active a developer/org is, wants backlog/stale-PR or hotfix/revert counts, or wants a portfolio/contribution dashboard. Accepts owner/name, a bare owner, a username, or any GitHub URL. Produces an HTML dashboard.
---

# GitHub Audit

Generate a PR-activity dashboard for a repo, a user/org's whole portfolio, or one
person's contributions across all repos.

## Prerequisites

- The `gh` CLI must be installed and authenticated (`gh auth status`). If it is
  not, tell the user and stop — do not estimate or fabricate any numbers.

## Steps

1. **Get the target and pick the mode.** Three modes — the reference plus what the
   user is asking for decides which. GitHub URLs work everywhere (`https://github.com/...`,
   `.git`/SSH/scp forms, deep links, bare `https://github.com/owner`).
   - `owner/name` → **single-repo** audit.
   - `owner` + "their repos / what this org ships" → **portfolio** over repos they own.
   - `owner` + "their work / what this person did / contributions" → **author** audit
     of PRs they authored *across all repos* (any org). Use this when the person's
     work lives in repos they don't own — a portfolio of a personal account misses it.
   If the user gave nothing identifiable, ask.

2. **Run the audit script** from the skill directory (pass the reference verbatim —
   quote URLs):

   - Single repo: `python3 scripts/audit.py <owner/name | repo-url>`
     Flags: `--weeks N` (4), `--months N` (3), `--limit N` (500 PRs).
   - User/org portfolio: `python3 scripts/audit_user.py <owner | owner-url>`
     Flags: same, plus `--repo-limit N` (300 max repos). Per-repo progress prints
     to stderr; transient `gh` errors auto-retry, and any repo that still fails is
     recorded in the output's `skipped` list rather than aborting the run.
   - Author contributions: `python3 scripts/audit_author.py <username | user-url>`
     Flags: `--weeks`, `--months`, `--limit N` (1000 PRs). Uses `gh search prs`, so
     it has no PR-size data (search omits additions/deletions); flow, merge rate,
     by-repo / by-org breakdown, and open-PR backlog are all present.

3. **On error:** if the script exits non-zero, show the user its stderr verbatim
   (it is usually an auth or repo-access problem). Do not proceed to render. The
   scripts already retry transient 5xx/network failures, so a non-zero exit is a
   real problem, not a blip.

4. **Render the dashboard.** Replace the single token `{{DATA_JSON}}` with the exact
   JSON the script printed, and publish as an HTML Artifact:
   - Single repo → `templates/dashboard.html`, titled `Repo Audit — <owner/name>`.
   - Portfolio → `templates/portfolio.html`, titled `Portfolio Audit — <owner>`.
   - Author → `templates/author.html`, titled `Contribution Audit — <username>`.

5. **Summarize** in one or two lines. Single repo: total PRs opened/merged, number
   of contributors, hotfix/revert counts. Portfolio: active/total repos, org-wide
   PRs opened/merged, contributor count. Author: PRs opened/merged, merge rate, and
   how many repos/orgs the work spans — then point to the dashboard.

## Notes

- All counting is done by the scripts; never re-tally numbers yourself.
- `opened`/`closed`/`merged` are each bucketed by their own timestamp, so a PR
  opened in one week and merged in another contributes to different buckets.
- If a script prints a `warning: hit --limit` / `hit --repo-limit` line on stderr,
  re-run with a higher cap. This matters most for the backlog metric, since
  newest-first fetching truncates the *oldest* (and often most stale) open PRs.
