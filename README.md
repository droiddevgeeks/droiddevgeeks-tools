# github-repo-audit

A Claude Code skill that audits one GitHub repo's PR activity and renders an
HTML dashboard.

## Install

Clone the repo straight into your Claude skills directory:

    git clone https://github.com/droiddevgeeks/github-repo-audit \
      ~/.claude/skills/github-repo-audit

Already cloned elsewhere? Copy it in from the parent of the clone:

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
