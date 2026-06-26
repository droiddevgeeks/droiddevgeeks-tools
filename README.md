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
