"""
Load test for the pages and endpoints that serve stored reports.

Every request here is answered from the database. Nothing starts a new analysis, so
GitHub is never called and no rate limit is involved. Seed the database first with
tests/load/seed_reports.py. The full procedure is in the README ("Performance").

    locust -f tests/load/locustfile.py --headless -u 30 -r 10 -t 60s \
        --host http://127.0.0.1:8811 --csv load-results
"""

import random

from locust import HttpUser, between, task


class Visitor(HttpUser):
    """Someone browsing reports: reads a report, scrolls the history, copies a badge."""

    # Think time between actions, so N users are not N requests in a tight loop
    wait_time = between(0.2, 1.0)

    def on_start(self) -> None:
        """Learns which reports exist, the way a visitor would from the history page."""
        listing = self.client.get("/api/v1/analyses?limit=100", name="setup: list").json()
        self.reports = [
            (item["id"], item["repo_owner"], item["repo_name"]) for item in listing["items"]
        ]
        self.total = listing["total"]

    def pick(self) -> tuple[int, str, str]:
        return random.choice(self.reports)

    def get_ok(self, path: str, name: str) -> None:
        """A GET that counts as a failure unless the answer is 200."""
        with self.client.get(path, name=name, catch_response=True) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")

    @task(6)
    def report_page(self) -> None:
        self.get_ok(f"/analysis/{self.pick()[0]}", "GET /analysis/{id}")

    @task(3)
    def history_page(self) -> None:
        self.get_ok(
            random.choice(["/history", "/history?sort=score_high", "/history?q=project&offset=20"]),
            "GET /history",
        )

    @task(3)
    def api_list(self) -> None:
        offset = random.randrange(0, max(1, self.total - 20))
        self.get_ok(f"/api/v1/analyses?limit=20&offset={offset}", "GET /api/v1/analyses")

    @task(2)
    def api_detail(self) -> None:
        self.get_ok(f"/api/v1/analyses/{self.pick()[0]}", "GET /api/v1/analyses/{id}")

    @task(4)
    def badge(self) -> None:
        _, owner, name = self.pick()
        self.get_ok(f"/badge/{owner}/{name}.svg", "GET /badge/{owner}/{repo}.svg")

    @task(1)
    def latest_report(self) -> None:
        # Redirects to the newest stored report of the repository
        _, owner, name = self.pick()
        self.get_ok(f"/repo/{owner}/{name}", "GET /repo/{owner}/{repo}")

    @task(1)
    def markdown_export(self) -> None:
        self.get_ok(f"/api/v1/analyses/{self.pick()[0]}/markdown", "GET /markdown")

    @task(1)
    def compare_stored(self) -> None:
        # Two different repositories (comparing a repository with itself is rejected)
        first = self.pick()
        second = random.choice([r for r in self.reports if r[1:] != first[1:]])
        (_, owner_a, name_a), (_, owner_b, name_b) = first, second
        self.get_ok(f"/compare?a={owner_a}/{name_a}&b={owner_b}/{name_b}", "GET /compare (stored)")
