import importlib.util
import pathlib
import unittest
from unittest import mock


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
MODULE_PATH = REPO_ROOT / "scripts" / "generate_dashboard.py"


spec = importlib.util.spec_from_file_location("generate_dashboard", MODULE_PATH)
generate_dashboard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(generate_dashboard)


class ValidateJiraAccessTests(unittest.TestCase):
    def test_validate_jira_access_checks_dashboard_search_permissions(self):
        with (
            mock.patch.object(generate_dashboard, "jira_post") as jira_post,
            mock.patch.object(generate_dashboard, "jira_get") as jira_get,
        ):
            generate_dashboard.validate_jira_access()

        jira_post.assert_called_once_with(
            "search/jql",
            {
                "jql": 'project in (LEF, LEM, LRF) AND created >= "2026-01-01" ORDER BY created DESC',
                "maxResults": 1,
                "fields": ["summary"],
            },
        )
        jira_get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
