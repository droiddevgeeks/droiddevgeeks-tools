"""Audit one GitHub repo's PR activity. Stdlib only."""

from datetime import datetime, timedelta, date

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


def parse_dt(s):
    if not s:
        return None
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def week_start(d):
    return d - timedelta(days=d.weekday())


def month_key(d):
    return f"{d.year:04d}-{d.month:02d}"


def _month_list(now, months):
    out = []
    for i in range(months - 1, -1, -1):
        yy, mm = now.year, now.month - i
        while mm <= 0:
            mm += 12
            yy -= 1
        out.append(f"{yy:04d}-{mm:02d}")
    return out


def bucket_by_week(prs, now, weeks=4):
    cur = week_start(now.date())
    starts = [cur - timedelta(weeks=i) for i in range(weeks - 1, -1, -1)]
    idx = {s: {"week_start": s.isoformat(), "opened": 0, "closed": 0, "merged": 0}
           for s in starts}
    valid = set(starts)
    for pr in prs:
        for field, key in (("createdAt", "opened"), ("closedAt", "closed"),
                           ("mergedAt", "merged")):
            dt = parse_dt(pr.get(field))
            if dt and week_start(dt.date()) in valid:
                idx[week_start(dt.date())][key] += 1
    return [idx[s] for s in starts]


def bucket_by_month(prs, now, months=3):
    keys = _month_list(now, months)
    valid = set(keys)
    idx = {k: {"month": k, "opened": 0, "closed": 0, "merged": 0} for k in keys}
    for pr in prs:
        for field, key in (("createdAt", "opened"), ("closedAt", "closed"),
                           ("mergedAt", "merged")):
            dt = parse_dt(pr.get(field))
            if dt and month_key(dt.date()) in valid:
                idx[month_key(dt.date())][key] += 1
    return [idx[k] for k in keys]


def contributors(prs):
    counts = {}
    for pr in prs:
        author = pr.get("author") or {}
        login = author.get("login") or "(unknown)"
        counts[login] = counts.get(login, 0) + 1
    items = [{"login": k, "count": v} for k, v in counts.items()]
    items.sort(key=lambda x: (-x["count"], x["login"]))
    return items


def build_report(prs, repo, now, weeks=4, months=3):
    weekly = bucket_by_week(prs, now, weeks)
    monthly = bucket_by_month(prs, now, months)
    since = min(
        date.fromisoformat(weekly[0]["week_start"]),
        date.fromisoformat(monthly[0]["month"] + "-01"),
    )
    in_window = [
        pr for pr in prs
        if (parse_dt(pr.get("createdAt")) or now).date() >= since
    ]
    contribs = contributors(in_window)
    totals = {
        "opened": len(in_window),
        "closed": sum(1 for pr in in_window if pr.get("closedAt")),
        "merged": sum(1 for pr in in_window if pr.get("mergedAt")),
        "hotfix": sum(1 for pr in in_window if classify(pr)["is_hotfix"]),
        "revert": sum(1 for pr in in_window if classify(pr)["is_revert"]),
        "contributors": len(contribs),
    }
    return {
        "repo": repo,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": {"weeks": weeks, "months": months, "since": since.isoformat()},
        "weekly": weekly,
        "monthly": monthly,
        "contributors": contribs,
        "totals": totals,
    }
