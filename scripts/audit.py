"""Audit one GitHub repo's PR activity. Stdlib only."""

HOTFIX_PREFIX = "hotfix/"
REVERT_TITLE_PREFIX = 'Revert "'
REVERT_LABEL = "revert"


def classify(pr):
    branch = (pr.get("headRefName") or "").lower()
    title = pr.get("title") or ""
    labels = [(l.get("name") or "").lower() for l in (pr.get("labels") or [])]
    is_hotfix = branch.startswith(HOTFIX_PREFIX)
    is_revert = (
        title.startswith(REVERT_TITLE_PREFIX)
        or branch.startswith("revert/")
        or branch.startswith("revert-")
        or REVERT_LABEL in labels
    )
    return {"is_hotfix": is_hotfix, "is_revert": is_revert}
