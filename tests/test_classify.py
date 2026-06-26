import unittest
from scripts.audit import classify


def pr(title="x", branch="feature/x", labels=None):
    return {"title": title, "headRefName": branch, "labels": labels or []}


class TestClassify(unittest.TestCase):
    def test_hotfix_branch(self):
        self.assertTrue(classify(pr(branch="hotfix/payment-crash"))["is_hotfix"])

    def test_hotfix_case_insensitive(self):
        self.assertTrue(classify(pr(branch="HotFix/Thing"))["is_hotfix"])

    def test_plain_branch_is_not_hotfix(self):
        self.assertFalse(classify(pr(branch="feature/login"))["is_hotfix"])

    def test_revert_by_title(self):
        self.assertTrue(classify(pr(title='Revert "Add login"'))["is_revert"])

    def test_revert_by_branch_slash(self):
        self.assertTrue(classify(pr(branch="revert/login"))["is_revert"])

    def test_revert_by_branch_dash(self):
        self.assertTrue(classify(pr(branch="revert-abc123-main"))["is_revert"])

    def test_revert_by_label(self):
        self.assertTrue(classify(pr(labels=[{"name": "Revert"}]))["is_revert"])

    def test_plain_pr_is_neither(self):
        c = classify(pr())
        self.assertFalse(c["is_hotfix"])
        self.assertFalse(c["is_revert"])

    def test_both_hotfix_and_revert(self):
        c = classify(pr(title='Revert "x"', branch="hotfix/x"))
        self.assertTrue(c["is_hotfix"])
        self.assertTrue(c["is_revert"])

    def test_missing_fields_safe(self):
        c = classify({})
        self.assertFalse(c["is_hotfix"])
        self.assertFalse(c["is_revert"])


if __name__ == "__main__":
    unittest.main()
