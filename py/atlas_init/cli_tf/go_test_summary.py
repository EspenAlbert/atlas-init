import logging
from datetime import date, datetime, timedelta
from functools import total_ordering

from model_lib import Entity
from pydantic import Field, model_validator
from zero_3rdparty import datetime_utils

from atlas_init.cli_tf.go_test_run import GoTestRun, GoTestStatus

logger = logging.getLogger(__name__)
_COMPLETE_STATUSES = {GoTestStatus.PASS, GoTestStatus.FAIL}


@total_ordering
class GoTestSummary(Entity):
    name: str
    results: list[GoTestRun] = Field(default_factory=list)

    @model_validator(mode="after")
    def sort_results(self):
        self.results.sort()
        return self

    @property
    def total_completed(self) -> int:
        return sum((r.status in _COMPLETE_STATUSES for r in self.results), 0)

    @property
    def success_rate(self) -> float:
        total = self.total_completed
        if total == 0:
            logger.warning(f"No results to calculate success rate for {self.name}")
            return 0
        return sum(r.status == "PASS" for r in self.results) / total

    @property
    def is_skipped(self) -> bool:
        return all(r.status == GoTestStatus.SKIP for r in self.results)

    @property
    def success_rate_human(self) -> str:
        return f"{self.success_rate:.2%}"

    def last_pass_human(self) -> str:
        return next(
            (f"Passed {test.when}" for test in reversed(self.results) if test.status == GoTestStatus.PASS),
            "never passed",
        )

    def __lt__(self, other) -> bool:
        if not isinstance(other, GoTestSummary):
            raise TypeError
        return (self.success_rate, self.name) < (other.success_rate, other.name)

    def select_tests(self, date: date) -> list[GoTestRun]:
        return [r for r in self.results if r.ts.date() == date]


def summary_str(summary: GoTestSummary, start_date: datetime, end_date: datetime) -> str:
    return "\n".join(
        [
            f"## {summary.name}",
            f"Success rate: {summary.success_rate_human}",
            "",
            "### Timeline",
            *timeline_lines(summary, start_date, end_date),
            "",
            *failure_details(summary),
        ]
    )


def timeline_lines(summary: GoTestSummary, start_date: datetime, end_date: datetime) -> list[str]:
    lines = []
    one_day = timedelta(days=1)
    for active_date in datetime_utils.day_range(start_date.date(), (end_date + one_day).date(), one_day):
        active_tests = summary.select_tests(active_date)
        if not active_tests:
            lines.append(f"{active_date:%Y-%m-%d}: MISSING")
            continue

        tests_str = ", ".join(format_test_oneline(t) for t in active_tests)
        lines.append(f"{active_date:%Y-%m-%d}: {tests_str}")
    return lines


def failure_details(summary: GoTestSummary) -> list[str]:
    lines = ["## Failures"]
    for test in summary.results:
        if test.status == GoTestStatus.FAIL:
            lines.extend(
                (
                    f"### {test.when} {format_test_oneline(test)}",
                    test.finish_summary(),
                    "",
                )
            )
    return lines


def format_test_oneline(test: GoTestRun) -> str:
    return f"[{test.status} {test.runtime_human}]({test.url})"
