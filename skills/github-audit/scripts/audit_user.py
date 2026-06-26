"""Audit every repo of a GitHub user/org into one portfolio JSON. Stdlib only."""

from audit import main_user

if __name__ == "__main__":
    raise SystemExit(main_user())
