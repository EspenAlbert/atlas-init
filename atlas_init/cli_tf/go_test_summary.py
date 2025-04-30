import logging
from datetime import date, datetime, timedelta
from functools import total_ordering

from model_lib import Entity
from pydantic import Field, model_validator
from zero_3rdparty import datetime_utils, file_utils

from atlas_init.cli_tf.github_logs import summary_dir
from atlas_init.cli_tf.go_test_run import GoTestRun, GoTestStatus
from atlas_init.cli_tf.go_test_tf_error import GoTestError

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

    @property
    def group_name(self) -> str:
        return next((r.group_name for r in self.results if r.group_name), "unknown-group")

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


def create_detailed_summary(
    summary_name: str,
    end_test_date: datetime,
    start_test_date: datetime,
    test_results: dict[str, list[GoTestRun]],
    expected_names: set[str] | None = None,
) -> list[str]:
    summary_dir_path = summary_dir(summary_name)
    if summary_dir_path.exists():
        file_utils.clean_dir(summary_dir_path)
    summaries = [GoTestSummary(name=name, results=runs) for name, runs in test_results.items()]
    top_level_summary = ["# SUMMARY OF ALL TESTS name (success rate)"]
    summaries = [summary for summary in summaries if summary.results and not summary.is_skipped]
    if expected_names and (skipped_names := expected_names - {summary.name for summary in summaries}):
        logger.warning(f"skipped test names: {'\n'.join(skipped_names)}")
        top_level_summary.append(f"Skipped tests: {', '.join(skipped_names)}")
    for summary in sorted(summaries):
        test_summary_path = summary_dir_path / f"{summary.success_rate_human}_{summary.name}.md"
        test_summary_md = summary_str(summary, start_test_date, end_test_date)
        file_utils.ensure_parents_write_text(test_summary_path, test_summary_md)
        top_level_summary.append(
            f"- {summary.name} - {summary.group_name} ({summary.success_rate_human}) ({summary.last_pass_human()}) ('{test_summary_path}')"
        )
    return top_level_summary


def create_short_summary(test_results: dict[str, list[GoTestRun]], failing_names: list[str]) -> list[str]:
    summary = ["# SUMMARY OF FAILING TESTS"]
    summary_fail_details: list[str] = ["# FAIL DETAILS"]

    for fail_name in failing_names:
        fail_tests = test_results[fail_name]
        summary.append(f"- {fail_name} has {len(fail_tests)} failures:")
        summary.extend(
            f"  - [{fail_run.when} failed in {fail_run.runtime_human}]({fail_run.url})" for fail_run in fail_tests
        )
        summary_fail_details.append(f"\n\n ## {fail_name} details:")
        summary_fail_details.extend(f"```\n{fail_run.finish_summary()}\n```" for fail_run in fail_tests)
    logger.info("\n".join(summary_fail_details))
    return summary


def create_test_report(
    runs: list[GoTestRun],
    errors: list[GoTestError],
    *,
    indent_size=4,
    max_runs=10,
) -> str:
    """
    Format of return string:
    - Found XX TestRuns in {",".join(envs)} (if only one day "on {YYYY-MM-DD}", else "between {YYYY-MM-DD}-{YYYY-MM-DD}"), YY unique tests, YY Errors, ZZ Skipped, PP Passed
    - Error Types:
        - error classification: pkg/TestName, pkg/TestName
    - Lowest pass rate last 7 days
        - `22%` pkg/TestName, last `PASS` y days ago, {classifications}
    - Lowest QA pass rate (last 14 days)
        - Same format
    - Longest time since `PASS`
        - (y days ago) pkg/TestName
    - Slowest tests
        - 3h 25s, pkg/TestName (Status) {maybe_classification}
    """
    single_indent = " " * indent_size
    if not runs:
        return "No test runs found"
    run_delta = GoTestRun.run_delta(runs)
    pkg_test_names = {run.name_with_package for run in runs}
    skipped = sum(run.status == GoTestStatus.SKIP for run in runs)
    passed = sum(run.status == GoTestStatus.PASS for run in runs)
    envs = {run.env for run in runs if run.env}
    envs_str = ", ".join(sorted(envs))
    branches = {run.branch for run in runs if run.branch}
    branches_str = (
        "from " + ", ".join(sorted(branches)) + " branches:" if len(branches) > 1 else f"from {branches.pop()} branch:"
    )
    lines = [
        f"# Found {len(runs)} TestRuns in {envs_str} {run_delta} {branches_str}: {len(pkg_test_names)} unique tests, {len(errors)} Errors, {skipped} Skipped, {passed} Passed"
    ]
    if errors:
        lines.append("\n\n## Errors Overview")
        lines.extend(error_overview_lines(errors, single_indent))
    for env in envs:
        env_runs = [run for run in runs if run.env == env]
        if len(env_runs) > 1:
            lines.append(f"\n\n## {env.upper()} Had {len(env_runs)} runs")
            lines.extend(env_summary_lines(env_runs, max_runs, single_indent))
    if errors:
        lines.append("\n\n## Errors Details")
        lines.extend(error_details(errors))
    return "\n".join(lines)


def error_overview_lines(errors: list[GoTestError], single_indent: str) -> list[str]:
    lines = []
    grouped_errors = GoTestError.group_by_classification(errors)
    if errors_unclassified := grouped_errors.unclassified:
        lines.append(f"- Found {len(grouped_errors.unclassified)} unclassified errors:")
        lines.extend(f"{single_indent}- {error.header}" for error in errors_unclassified)
    if errors_by_class := grouped_errors.classified:
        for classification, errors in errors_by_class.items():
            lines.append(f"- Error Type {classification}:")
            lines.extend(f"{single_indent}- {error.header}" for error in errors)
    return lines


def env_summary_lines(env_runs: list[GoTestRun], max_runs: int, single_indent: str) -> list[str]:
    lines = [f"- Lowest pass rate: {GoTestRun.run_delta(env_runs)}"]
    for pass_rate, name, name_tests in GoTestRun.lowest_pass_rate(env_runs, max_tests=max_runs):
        ran_count_str = f"ran {len(name_tests)} times" if len(name_tests) > 1 else "ran 1 time"
        if last_pass := GoTestRun.last_pass(name_tests):
            lines.append(f"{single_indent}- {pass_rate:.2%} {name} ({ran_count_str}) last PASS {last_pass}")
        else:
            lines.append(f"{single_indent}- {pass_rate:.2%} {name} ({ran_count_str}) never passed")
    if pass_stats := GoTestRun.last_pass_stats(env_runs, max_tests=max_runs):
        lines.append(f"- Longest time since `{GoTestStatus.PASS}`: {GoTestRun.run_delta(env_runs)}")
        lines.extend(
            f"{single_indent}- {pass_stat.pass_when} {pass_stat.name_with_package}" for pass_stat in pass_stats
        )
    lines.append(f"- Slowest tests: {GoTestRun.run_delta(env_runs)}")
    for time_stat in GoTestRun.slowest_tests(env_runs):
        avg_time_str = (
            f"(avg = {time_stat.average_seconds:.2f}s across {len(time_stat.runs)} runs)"
            if time_stat.average_seconds
            else ""
        )
        lines.append(
            f"{single_indent}- {time_stat.slowest_duration} {time_stat.name_with_package} {avg_time_str}".rstrip()
        )
    return lines


def error_details(errors: list[GoTestError]) -> list[str]:
    return [
        f"### {error.run.name_with_package} in {error.run.env}\nerror class: (bot={error.bot_error_class}, human={error.human_error_class})\n{error.details}\n```log\n{error.run.output_lines_str}```"
        for error in errors
    ]
