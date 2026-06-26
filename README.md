# github-repo-audit

A Claude Code skill that audits one GitHub repo's PR activity and renders a
self-contained HTML dashboard. Packaged as a Claude Code plugin.

## Install (plugin — recommended)

This repo is both the plugin and its own marketplace. In Claude Code:

    /plugin marketplace add droiddevgeeks/github-repo-audit
    /plugin install github-repo-audit@droiddevgeeks

Then invoke it: "audit the cli/cli repo". The skill is namespaced as
`/github-repo-audit:github-repo-audit`.

To update later, bump the version and the plugin manager pulls the new release.

## Install (manual copy — alternative)

If you'd rather not use the plugin system, copy just the skill folder into your
personal skills directory:

    git clone https://github.com/droiddevgeeks/github-repo-audit /tmp/github-repo-audit
    cp -r /tmp/github-repo-audit/skills/github-repo-audit ~/.claude/skills/github-repo-audit

Invoked this way the skill is unnamespaced: just "audit the cli/cli repo".

## Requirements

- `gh` CLI, authenticated (`gh auth status`)
- Python 3 (standard library only)

## Run the script directly

From `skills/github-repo-audit/`:

    python3 scripts/audit.py owner/name --weeks 4 --months 3

Prints a JSON report to stdout.

## Test

From `skills/github-repo-audit/`:

    python3 -m unittest discover -s tests -v

## Layout

    .claude-plugin/
      plugin.json          # plugin manifest
      marketplace.json     # marketplace catalog (this repo serves itself)
    skills/
      github-repo-audit/
        SKILL.md           # skill instructions
        scripts/audit.py   # gh fetch + bucketing, emits JSON
        templates/         # self-contained HTML dashboard shell
        tests/             # unittest suite
