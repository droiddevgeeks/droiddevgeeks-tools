"""Audit GitHub PR activity — single repo, user/org portfolio, or author. Stdlib only."""

import re
import sys
import json
import argparse
import subprocess
from datetime import datetime, timedelta, date, timezone

HOTFIX_PREFIX = "hotfix/"
REVERT_TITLE_PREFIX = 'Revert "'
REVERT_LABEL = "revert"


def _ref_parts(s):
    """Strip scheme/host/user/.git from any GitHub reference -> path segments."""
    s = (s or "").strip()
    if not s:
        raise ValueError("empty reference")
    s = re.sub(r"\.git/?$", "", s)            # trailing .git (with optional /)
    s = re.sub(r"^[a-zA-Z][a-zA-Z0-9+.\-]*://", "", s)  # scheme://
    s = re.sub(r"^[^/@]+@", "", s)            # user@
    s = s.replace(":", "/", 1)                # scp host:path -> host/path
    parts = [p for p in s.split("/") if p]
    if parts and "." in parts[0]:             # drop leading host (e.g. github.com)
        parts = parts[1:]
    return parts


def normalize_repo(s):
    """Reduce any common GitHub repo reference to 'owner/name'.

    Accepts bare 'owner/name', https/ssh/git URLs (with or without a .git
    suffix or trailing slash), scp-style 'git@host:owner/name', and deep
    links like '.../owner/name/pull/42'.
    """
    parts = _ref_parts(s)
    if len(parts) < 2:
        raise ValueError(f"cannot parse owner/name from {s!r}")
    return f"{parts[0]}/{parts[1]}"


def normalize_owner(s):
    """Reduce a user/org reference (bare name or URL) to just the owner."""
    parts = _ref_parts(s)
    if not parts:
        raise ValueError(f"cannot parse owner from {s!r}")
    return parts[0]


_TRANSIENT = ("502", "503", "504", "bad gateway", "gateway time", "service unavailable",
              "timeout", "timed out", "i/o timeout", "connection reset", "eof")


def _is_transient(stderr):
    msg = (stderr or "").lower()
    return any(t in msg for t in _TRANSIENT)


def _gh(cmd, retries=3, sleep=None):
    """Run a gh command, retrying transient (5xx / network) failures with backoff.

    Permanent errors (404, auth) fail immediately. Returns stdout on success.
    """
    import time
    sleep = sleep or time.sleep
    last = ""
    for attempt in range(retries + 1):
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode == 0:
            return result.stdout
        last = result.stderr.strip()
        if attempt < retries and _is_transient(last):
            sleep(min(2 ** attempt, 8))
            continue
        break
    raise RuntimeError(f"gh failed: {last}")


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


SIZE_BANDS = [  # (label, lower-inclusive bound on lines changed)
    ("XS", 0), ("S", 10), ("M", 50), ("L", 200), ("XL", 500),
]


def _lines(pr):
    return (pr.get("additions") or 0) + (pr.get("deletions") or 0)


def _percentile(sorted_vals, pct):
    """Nearest-rank percentile. pct in [0,1]. Empty -> 0."""
    if not sorted_vals:
        return 0
    import math
    rank = max(1, math.ceil(pct * len(sorted_vals)))
    return sorted_vals[rank - 1]


def size_distribution(prs):
    counts = {label: 0 for label, _ in SIZE_BANDS}
    lines = []
    largest = None
    for pr in prs:
        n = _lines(pr)
        lines.append(n)
        label = SIZE_BANDS[0][0]
        for lbl, lo in SIZE_BANDS:
            if n >= lo:
                label = lbl
        counts[label] += 1
        if largest is None or n > largest["lines"]:
            largest = {"number": pr.get("number"), "lines": n}
    lines.sort()
    ranges = {"XS": "<10", "S": "10-49", "M": "50-199", "L": "200-499", "XL": "500+"}
    return {
        "buckets": [{"label": lbl, "range": ranges[lbl], "count": counts[lbl]}
                    for lbl, _ in SIZE_BANDS],
        "median_lines": _percentile(lines, 0.5),
        "p90_lines": _percentile(lines, 0.9),
        "largest": largest if lines else None,
    }


AGE_BANDS = [  # (label, lower-inclusive age in days)
    ("<7d", 0), ("7-30d", 7), ("30-90d", 30), (">90d", 90),
]
STALE_DAYS = 30


def backlog(prs, now):
    counts = {label: 0 for label, _ in AGE_BANDS}
    open_total = 0
    stale = 0
    oldest_days = None
    for pr in prs:
        if (pr.get("state") or "").upper() != "OPEN":
            continue
        created = parse_dt(pr.get("createdAt"))
        if not created:
            continue
        open_total += 1
        age = (now.date() - created.date()).days
        label = AGE_BANDS[0][0]
        for lbl, lo in AGE_BANDS:
            if age >= lo:
                label = lbl
        counts[label] += 1
        if oldest_days is None or age > oldest_days:
            oldest_days = age
        updated = parse_dt(pr.get("updatedAt"))
        if updated and (now.date() - updated.date()).days >= STALE_DAYS:
            stale += 1
    return {
        "open_total": open_total,
        "age_buckets": [{"label": lbl, "count": counts[lbl]} for lbl, _ in AGE_BANDS],
        "stale_30d": stale,
        "oldest_days": oldest_days,
    }


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
    backlog_stats = backlog(prs, now)
    size_stats = size_distribution(in_window)
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
        "backlog": backlog_stats,
        "size": size_stats,
        "totals": totals,
    }


GH_FIELDS = ("number,title,author,createdAt,closedAt,mergedAt,updatedAt,state,"
             "headRefName,labels,additions,deletions,changedFiles")


def fetch_prs(repo, limit=500):
    cmd = ["gh", "pr", "list", "--repo", repo, "--state", "all",
           "--limit", str(limit), "--json", GH_FIELDS]
    prs = json.loads(_gh(cmd) or "[]")
    if len(prs) >= limit:
        print(f"warning: hit --limit {limit}; older PRs may be missing",
              file=sys.stderr)
    return prs


REPO_FIELDS = "nameWithOwner,isFork,isArchived,stargazerCount,pushedAt,visibility"


def list_repos(owner, limit=300):
    cmd = ["gh", "repo", "list", owner, "--limit", str(limit), "--json", REPO_FIELDS]
    repos = json.loads(_gh(cmd) or "[]")
    if len(repos) >= limit:
        print(f"warning: hit --repo-limit {limit}; more repos may exist",
              file=sys.stderr)
    return repos


def build_portfolio(owner, entries, now, weeks=4, months=3):
    """Aggregate per-repo reports into one portfolio.

    entries: list of {"meta": {...}, "report": <build_report output>}.
    """
    repos = []
    org_contrib = {}
    agg = {"opened": 0, "merged": 0, "closed": 0, "hotfix": 0, "revert": 0,
           "open_backlog": 0, "stale": 0}
    for e in entries:
        rep, meta = e["report"], e["meta"]
        T = rep.get("totals", {})
        B = rep.get("backlog") or {}
        S = rep.get("size") or {}
        for c in rep.get("contributors", []):
            org_contrib[c["login"]] = org_contrib.get(c["login"], 0) + c["count"]
        for k in ("opened", "merged", "closed", "hotfix", "revert"):
            agg[k] += T.get(k, 0)
        agg["open_backlog"] += B.get("open_total", 0)
        agg["stale"] += B.get("stale_30d", 0)
        repos.append({
            "repo": rep["repo"],
            "stars": meta.get("stars", 0),
            "isFork": meta.get("isFork", False),
            "isArchived": meta.get("isArchived", False),
            "pushedAt": meta.get("pushedAt"),
            "limit_hit": meta.get("limit_hit", False),
            "opened": T.get("opened", 0),
            "merged": T.get("merged", 0),
            "closed": T.get("closed", 0),
            "hotfix": T.get("hotfix", 0),
            "revert": T.get("revert", 0),
            "contributors": T.get("contributors", 0),
            "open_backlog": B.get("open_total", 0),
            "stale": B.get("stale_30d", 0),
            "oldest_days": B.get("oldest_days"),
            "median_lines": S.get("median_lines", 0),
            "p90_lines": S.get("p90_lines", 0),
        })
    repos.sort(key=lambda x: (-x["opened"], -x["merged"], -x["stars"], x["repo"]))
    org_top = sorted(
        [{"login": k, "count": v} for k, v in org_contrib.items()],
        key=lambda x: (-x["count"], x["login"]))
    totals = {
        "repos": len(repos),
        "active_repos": sum(1 for r in repos if r["opened"] > 0),
        "contributors": len(org_contrib),
        **agg,
    }
    return {
        "owner": owner,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": {"weeks": weeks, "months": months,
                   "since": _month_list(now, months)[0] + "-01"},
        "repos": repos,
        "contributors": org_top,
        "totals": totals,
    }


SEARCH_FIELDS = "number,title,state,createdAt,closedAt,updatedAt,repository,url"


def search_author_prs(author, limit=1000):
    cmd = ["gh", "search", "prs", "--author", author, "--sort", "created",
           "--order", "desc", "--limit", str(limit), "--json", SEARCH_FIELDS]
    prs = json.loads(_gh(cmd) or "[]")
    if len(prs) >= limit:
        print(f"warning: hit --limit {limit}; older PRs may be missing",
              file=sys.stderr)
    return prs


def _author_pr(pr):
    """Normalize a `gh search prs` record. state is open|merged|closed.

    Maps to the createdAt/mergedAt/closedAt shape the bucket helpers expect,
    where closedAt holds only *unmerged* closes (merged closes go to mergedAt).
    """
    state = (pr.get("state") or "").lower()
    closed = pr.get("closedAt")
    repo = (pr.get("repository") or {}).get("nameWithOwner") or "(unknown)"
    owner = repo.split("/")[0] if "/" in repo else repo
    return {
        "createdAt": pr.get("createdAt"),
        "mergedAt": closed if state == "merged" else None,
        "closedAt": closed if state == "closed" else None,
        "updatedAt": pr.get("updatedAt"),
        "state": state,
        "repo": repo,
        "owner": owner,
        "_closed": closed,
        "number": pr.get("number"),
        "title": pr.get("title"),
    }


def author_breakdown(norm, since):
    """Group normalized author PRs by repo and by owner, counting within window."""
    def hit(s):
        d = parse_dt(s)
        return bool(d) and d.date() >= since
    repos, orgs = {}, {}
    for p in norm:
        op = 1 if hit(p["createdAt"]) else 0
        mg = 1 if (p["state"] == "merged" and hit(p["_closed"])) else 0
        cl = 1 if (p["state"] == "closed" and hit(p["_closed"])) else 0
        opn = 1 if p["state"] == "open" else 0
        if not (op or mg or cl or opn):
            continue
        r = repos.setdefault(p["repo"], {
            "repo": p["repo"], "owner": p["owner"],
            "opened": 0, "merged": 0, "closed": 0, "open": 0})
        o = orgs.setdefault(p["owner"], {
            "owner": p["owner"], "opened": 0, "merged": 0, "closed": 0,
            "open": 0, "_repos": set()})
        for d, k in ((op, "opened"), (mg, "merged"), (cl, "closed"), (opn, "open")):
            r[k] += d
            o[k] += d
        o["_repos"].add(p["repo"])
    repo_list = sorted(repos.values(),
                       key=lambda x: (-(x["opened"] + x["merged"]), x["repo"]))
    org_list = sorted(
        [{**{k: v for k, v in o.items() if k != "_repos"}, "repos": len(o["_repos"])}
         for o in orgs.values()],
        key=lambda x: (-(x["opened"] + x["merged"]), x["owner"]))
    return repo_list, org_list


def build_author_report(prs, author, now, weeks=4, months=3):
    norm = [_author_pr(p) for p in prs]
    weekly = bucket_by_week(norm, now, weeks)
    monthly = bucket_by_month(norm, now, months)
    since = min(
        date.fromisoformat(weekly[0]["week_start"]),
        date.fromisoformat(monthly[0]["month"] + "-01"),
    )
    repos, orgs = author_breakdown(norm, since)
    bl = backlog(norm, now)
    opened = sum(r["opened"] for r in repos)
    merged = sum(r["merged"] for r in repos)
    closed = sum(r["closed"] for r in repos)
    totals = {
        "opened": opened,
        "merged": merged,
        "closed": closed,
        "merge_rate": round(merged / opened * 100) if opened else 0,
        "repos": len(repos),
        "orgs": len(orgs),
        "open_backlog": bl["open_total"],
        "stale": bl["stale_30d"],
    }
    return {
        "author": author,
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window": {"weeks": weeks, "months": months, "since": since.isoformat()},
        "weekly": weekly,
        "monthly": monthly,
        "repos": repos,
        "orgs": orgs,
        "backlog": bl,
        "totals": totals,
    }


def main(argv=None, fetch=fetch_prs, now=None):
    parser = argparse.ArgumentParser(description="Audit a GitHub repo's PR activity.")
    parser.add_argument("repo", help="owner/name or a GitHub repo URL")
    parser.add_argument("--weeks", type=int, default=4)
    parser.add_argument("--months", type=int, default=3)
    parser.add_argument("--limit", type=int, default=500)
    args = parser.parse_args(argv)
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        repo = normalize_repo(args.repo)
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    try:
        prs = fetch(repo, limit=args.limit)
    except RuntimeError as e:
        print(str(e), file=sys.stderr)
        return 1
    report = build_report(prs, repo, now, args.weeks, args.months)
    print(json.dumps(report, indent=2))
    return 0


def main_user(argv=None, list_fn=list_repos, fetch=fetch_prs, now=None):
    parser = argparse.ArgumentParser(
        description="Audit every repo of a GitHub user/org into one portfolio.")
    parser.add_argument("owner", help="user/org name or URL")
    parser.add_argument("--weeks", type=int, default=4)
    parser.add_argument("--months", type=int, default=3)
    parser.add_argument("--limit", type=int, default=500, help="PRs fetched per repo")
    parser.add_argument("--repo-limit", type=int, default=300, help="max repos to scan")
    args = parser.parse_args(argv)
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        owner = normalize_owner(args.owner)
        repos = list_fn(owner, args.repo_limit)
    except (ValueError, RuntimeError) as e:
        print(str(e), file=sys.stderr)
        return 1

    print(f"scanning {len(repos)} repos for {owner} ...", file=sys.stderr)
    entries, skipped = [], []
    for i, rm in enumerate(repos, 1):
        full = rm["nameWithOwner"]
        print(f"  [{i}/{len(repos)}] {full}", file=sys.stderr)
        try:
            prs = fetch(full, limit=args.limit)
            rep = build_report(prs, full, now, args.weeks, args.months)
            entries.append({"report": rep, "meta": {
                "stars": rm.get("stargazerCount", 0),
                "isFork": rm.get("isFork", False),
                "isArchived": rm.get("isArchived", False),
                "pushedAt": rm.get("pushedAt"),
                "limit_hit": len(prs) >= args.limit,
            }})
        except RuntimeError as e:
            print(f"    skipped: {e}", file=sys.stderr)
            skipped.append({"repo": full, "error": str(e)})

    portfolio = build_portfolio(owner, entries, now, args.weeks, args.months)
    portfolio["skipped"] = skipped
    print(json.dumps(portfolio, indent=2))
    return 0


def main_author(argv=None, search=search_author_prs, now=None):
    parser = argparse.ArgumentParser(
        description="Audit every PR a GitHub user authored, across all repos.")
    parser.add_argument("author", help="username or URL")
    parser.add_argument("--weeks", type=int, default=4)
    parser.add_argument("--months", type=int, default=3)
    parser.add_argument("--limit", type=int, default=1000, help="max PRs fetched")
    args = parser.parse_args(argv)
    if now is None:
        now = datetime.now(timezone.utc)
    try:
        author = normalize_owner(args.author)
        prs = search(author, limit=args.limit)
    except (ValueError, RuntimeError) as e:
        print(str(e), file=sys.stderr)
        return 1
    report = build_author_report(prs, author, now, args.weeks, args.months)
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
