# github-repo-audit

A Claude Code skill that audits one GitHub repo's PR activity and renders a
self-contained HTML dashboard. Packaged as a Claude Code plugin.

## Install (plugin — recommended)

This repo is both the plugin and its own marketplace. In Claude Code:

    /plugin marketplace add droiddevgeeks/github-repo-audit
    /plugin install droiddevgeeks-tools@droiddevgeeks

Then invoke it: "audit the cli/cli repo". The skill is namespaced as
`/droiddevgeeks-tools:github-audit` (plugin name : skill name).

To update later, bump the version and the plugin manager pulls the new release.

## Install (manual copy — alternative)

If you'd rather not use the plugin system, copy just the skill folder into your
personal skills directory:

    git clone https://github.com/droiddevgeeks/github-repo-audit /tmp/github-repo-audit
    cp -r /tmp/github-repo-audit/skills/github-audit ~/.claude/skills/github-audit

Invoked this way the skill is unnamespaced: just "audit the cli/cli repo".

## Usage

Once installed, just ask Claude Code in plain language. The skill triggers on
phrasing about PR activity, contributors, or hotfix/revert counts.

You can name the repo as `owner/name`, a GitHub URL, or `@username/repo` — Claude
extracts the `owner/name` either way:

    audit the cli/cli repo
    how active is facebook/react over the last 4 weeks?
    audit https://github.com/vercel/next.js
    who's contributing to torvalds/linux this month?
    how many hotfix or revert PRs did kubernetes/kubernetes have?

Claude runs the audit and renders an HTML dashboard artifact titled
`Repo Audit — <owner/name>`. If you don't give a repo, it asks for one.

## Requirements

- `gh` CLI, authenticated (`gh auth status`)
- Python 3 (standard library only)

## Run the script directly

The underlying script takes `owner/name` (not a URL). From
`skills/github-audit/`:

    python3 scripts/audit.py cli/cli
    python3 scripts/audit.py facebook/react --weeks 8 --months 6
    python3 scripts/audit.py kubernetes/kubernetes --limit 1000

Flags: `--weeks N` (default 4), `--months N` (default 3), `--limit N`
(default 500, the max PRs fetched). Prints a JSON report to stdout.

## Test

From `skills/github-audit/`:

    python3 -m unittest discover -s tests -v

## Layout

    .claude-plugin/
      plugin.json          # plugin manifest (name: droiddevgeeks-tools)
      marketplace.json     # marketplace catalog (this repo serves itself)
    skills/
      github-audit/
        SKILL.md           # skill instructions (name: github-audit)
        scripts/audit.py   # gh fetch + bucketing, emits JSON
        templates/         # self-contained HTML dashboard shell
        tests/             # unittest suite
