"""Audit every PR a GitHub user authored across all repos. Stdlib only."""

from audit import main_author

if __name__ == "__main__":
    raise SystemExit(main_author())
