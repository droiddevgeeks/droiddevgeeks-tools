---
name: github-audit
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
- If the script prints a `warning: hit --limit` line on stderr, the repo has more
  PRs than were fetched; re-run with a higher `--limit` for full coverage.
