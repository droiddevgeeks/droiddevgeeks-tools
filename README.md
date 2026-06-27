# droiddevgeeks-tools

A Claude Code plugin of droiddevgeeks's tools. Ships one skill, **github-audit**,
which audits GitHub pull-request activity and renders a self-contained HTML
dashboard (published as a Claude Artifact).

## What it does — three modes

The reference you give decides the mode:

| Mode | Input | Answers | Script | Template |
|------|-------|---------|--------|----------|
| **Repo** | `owner/name` | How healthy is one repo's PR flow? | `scripts/audit.py` | `templates/dashboard.html` |
| **Portfolio** | `owner` (user/org) | What do this account's *owned repos* look like? | `scripts/audit_user.py` | `templates/portfolio.html` |
| **Contributions** | `username` | What has this *person* shipped, across every repo? | `scripts/audit_author.py` | `templates/author.html` |

> **Repo vs. Contributions** — a portfolio of a *personal* account only sees repos
> that account *owns* (often just forks). To see a person's actual work in
> org-owned repos they contribute to, use the contributions mode.

## Install (plugin — recommended)

This repo is both the plugin and its own marketplace. In Claude Code:

    /plugin marketplace add droiddevgeeks/droiddevgeeks-tools
    /plugin install droiddevgeeks-tools@droiddevgeeks

Then try it — the quickest start is to audit your own work:

    show my contributions

The skill is namespaced as `/droiddevgeeks-tools:github-audit`. To update later,
bump the version in `plugin.json`, push, and run `/plugin update droiddevgeeks-tools`.

## Usage

Ask Claude Code in plain language — it picks the mode and the target. With no name,
it uses your current authenticated `gh` user, so the fastest first run is:

    show my contributions          # your PRs across every repo (current gh user)
    audit me                       # same thing

Or name a target — `owner/name`, a bare `owner`, a `username`, or any GitHub URL:

    audit the cli/cli repo
    audit https://github.com/vercel/next.js
    show me cashfree-tech's repo portfolio
    what has kishan-cashfree worked on?

## Run the scripts directly

From `skills/github-audit/`:

    # Single repo
    python3 scripts/audit.py cli/cli
    python3 scripts/audit.py https://github.com/facebook/react --weeks 8 --months 6

    # Whole user/org portfolio (one call per repo; sorted by activity)
    python3 scripts/audit_user.py cashfree-tech --repo-limit 50

    # One person's PRs across all repos and orgs
    python3 scripts/audit_author.py kishan-cashfree
    python3 scripts/audit_author.py            # no name → current gh user ("audit me")

`audit_author.py` and `audit_user.py` both default to the current authenticated
`gh` user (`gh api user`) when you omit the name.

Common flags: `--weeks N` (4), `--months N` (3), `--limit N` (PRs fetched — 500 for
repo/portfolio, 1000 for author). Portfolio adds `--repo-limit N` (300). Each script
prints JSON to stdout; the skill substitutes it into the matching template's
`{{DATA_JSON}}` token.

## What's measured

- **Flow** — PRs opened / merged / closed, weekly and monthly (each by its own date).
- **Contributors** — ranked by PRs authored, with bots (`app/*`, `*[bot]`,
  dependabot, renovate) detected and shown muted.
- **Backlog** — open PRs by age (`<7d / 7–30d / 30–90d / >90d`), stale count
  (no activity 30d+), and oldest open PR.
- **PR size** — lines-changed distribution (XS→XL), median, p90, largest PR.
  *(Repo and portfolio modes only — `gh search` omits diff size, so the
  contributions mode has no size data.)*
- **Velocity** — time-to-merge and first-review latency (p50 + p90), calendar
  time. Self-reviews and bots excluded; no-review PRs reported as a count.
  *(Repo and portfolio modes only — `gh search` omits review/merge timing, so
  the contributions mode has no velocity data.)*
- **Hotfix / revert** counts (repo mode).

## Requirements

- `gh` CLI, authenticated (`gh auth status`). All counting is done by the scripts;
  numbers are never estimated. Transient `gh` 5xx/network errors auto-retry.
- Python 3 (standard library only — no dependencies).

## Test

From `skills/github-audit/`:

    python3 -m unittest discover -s tests -t . -v

## Layout

    .claude-plugin/
      plugin.json          # plugin manifest (name: droiddevgeeks-tools)
      marketplace.json     # marketplace catalog (this repo serves itself)
    skills/
      github-audit/
        SKILL.md           # skill instructions (name: github-audit)
        scripts/
          audit.py         # single-repo audit + shared core
          audit_user.py    # user/org portfolio
          audit_author.py  # author contributions
        templates/         # dashboard.html, portfolio.html, author.html
        tests/             # unittest suite

## Notes

- `opened` / `closed` / `merged` are bucketed independently, so a PR opened in one
  period and merged in another contributes to different buckets.
- If a script warns `hit --limit` / `hit --repo-limit`, re-run with a higher cap —
  the backlog metric needs full coverage, since newest-first fetching truncates the
  oldest (and often most stale) open PRs.
