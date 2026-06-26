import io
import json
import unittest
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
from scripts.audit import main

NOW = datetime(2026, 6, 26, 12, 0, 0, tzinfo=timezone.utc)

FAKE_PRS = [
    {"author": {"login": "a"}, "createdAt": "2026-06-23T00:00:00Z",
     "closedAt": "2026-06-24T00:00:00Z", "mergedAt": "2026-06-24T00:00:00Z",
     "headRefName": "hotfix/x", "title": "fix", "labels": []},
]


class TestMain(unittest.TestCase):
    def test_prints_valid_json(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = main(["owner/name"], fetch=lambda repo, limit=500: FAKE_PRS, now=NOW)
        self.assertEqual(code, 0)
        data = json.loads(buf.getvalue())
        self.assertEqual(data["repo"], "owner/name")
        self.assertEqual(data["totals"]["hotfix"], 1)

    def test_gh_failure_returns_1(self):
        def boom(repo, limit=500):
            raise RuntimeError("gh failed: not authenticated")
        err = io.StringIO()
        with redirect_stderr(err):
            code = main(["owner/name"], fetch=boom, now=NOW)
        self.assertEqual(code, 1)
        self.assertIn("not authenticated", err.getvalue())


if __name__ == "__main__":
    unittest.main()
