from collections import Counter
from dataclasses import dataclass
import logging
from datetime import date, datetime, timedelta
from functools import total_ordering
from pathlib import Path

from model_lib import Entity
from pydantic import Field, model_validator
from zero_3rdparty import datetime_utils, file_utils

from atlas_init.cli_tf.github_logs import summary_dir
from atlas_init.cli_tf.go_test_run import GoTestRun, GoTestStatus
from atlas_init.cli_tf.go_test_tf_error import GoTestError, GoTestErrorClassification

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


@dataclass
class GoRunTestReport:
    summary: str
    error_details: str


def create_test_report(
    runs: list[GoTestRun],
    errors: list[GoTestError],
    *,
    indent_size=2,
    max_runs=20,
    env_name: str = "",
) -> GoRunTestReport:
    if env_name:
        runs = [run for run in runs if run.env == env_name]
        errors = [error for error in errors if error.run.env == env_name]
    single_indent = " " * indent_size
    if not runs:
        return GoRunTestReport(
            summary="No test runs found",
            error_details="",
        )
    run_delta = GoTestRun.run_delta(runs)
    pkg_test_names = {run.name_with_package for run in runs}
    skipped = sum(run.status == GoTestStatus.SKIP for run in runs)
    passed = sum(run.status == GoTestStatus.PASS for run in runs)
    envs = {run.env for run in runs if run.env}
    envs_str = ", ".join(sorted(envs))
    branches = {run.branch for run in runs if run.branch}
    branches_str = (
        "from " + ", ".join(sorted(branches)) + " branches" if len(branches) > 1 else f"from {branches.pop()} branch"
    )
    lines = [
        f"# Found {len(runs)} TestRuns in {envs_str} {run_delta} {branches_str}: {len(pkg_test_names)} unique tests, {len(errors)} Errors, {skipped} Skipped, {passed} Passed"
    ]
    if errors:
        env_name_str = f" in {env_name}" if env_name else ""
        lines.append(f"\n\n## Errors Overview{env_name_str}")
        lines.extend(error_overview_lines(errors, single_indent))
    for env in envs:
        env_runs = [run for run in runs if run.env == env]
        lines.append(f"\n\n## {env.upper()} Had {len(env_runs)} Runs")
        lines.extend(env_summary_lines(env_runs, max_runs, single_indent))
    if len(envs) > 1:
        lines.append(f"\n\n## All Environments Had {len(runs)} Runs")
        lines.extend(env_summary_lines(runs, max_runs, single_indent))
    error_detail_lines = []
    if errors:
        error_detail_lines.append("# Errors Details")
        error_detail_lines.extend(error_details(errors, include_env=len(envs) > 1))
    return GoRunTestReport(
        summary="\n".join(lines),
        error_details="\n".join(error_detail_lines),
    )


def error_overview_lines(errors: list[GoTestError], single_indent: str) -> list[str]:
    lines = []
    grouped_errors = GoTestError.group_by_classification(errors)
    if errors_unclassified := grouped_errors.unclassified:
        lines.append(f"- Found {len(grouped_errors.unclassified)} unclassified errors:")
        lines.extend(count_errors_by_test(single_indent, errors_unclassified))
    if errors_by_class := grouped_errors.classified:
        for classification, errors in errors_by_class.items():
            lines.append(f"- Error Type `{classification}`:")
            lines.extend(count_errors_by_test(single_indent, errors))
    return lines


def count_errors_by_test(indent: str, errors: list[GoTestError]) -> list[str]:
    lines: list[str] = []
    counter = Counter()
    for error in errors:
        counter[error.header(use_ticks=True)] += 1
    for error_header, count in counter.most_common():
        if count > 1:
            lines.append(f"{indent}- {count} x {error_header}")
        else:
            lines.append(f"{indent}- {error_header}")
    return sorted(lines)


def env_summary_lines(env_runs: list[GoTestRun], max_runs: int, single_indent: str) -> list[str]:
    lines: list[str] = []
    if pass_rates := GoTestRun.lowest_pass_rate(env_runs, max_tests=max_runs, include_single_run=False):
        lines.append(f"- Lowest pass rate: {GoTestRun.run_delta(env_runs)}")
        for pass_rate, name, name_tests in pass_rates:
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
            f"(avg = {time_stat.average_duration} across {len(time_stat.runs)} runs)"
            if time_stat.average_seconds
            else ""
        )
        lines.append(
            f"{single_indent}- {time_stat.slowest_duration} {time_stat.name_with_package} {avg_time_str}".rstrip()
        )
    return lines


def error_details(errors: list[GoTestError], include_env: bool) -> list[str]:
    lines: list[str] = []
    for name, name_errors in GoTestError.group_by_name_with_package(errors).items():
        lines.append(
            f"## {name} had {len(name_errors)} errors {GoTestRun.run_delta([error.run for error in name_errors])}",
        )
        for error in sorted(name_errors, reverse=True):  # newest first
            env_str = f" in {error.run.env} " if include_env and error.run.env else ""
            lines.extend(
                [
                    f"### Started @ {error.run.ts} {env_str}ran for ({error.run.runtime_human})",
                    f"- error classes: bot={error.bot_error_class}, human={error.human_error_class}",
                    f"- details summary: {error.short_description}",
                    f"- test output:\n```log\n{error.run.output_lines_str}\n```\n",
                ]
            )
    return lines


class TFCITestOutput(Entity):
    log_paths: list[Path] = Field(default_factory=list)
    found_tests: list[GoTestRun] = Field(default_factory=list)
    found_errors: list[GoTestError] = Field(default_factory=list)
    classified_errors: list[GoTestErrorClassification] = Field(default_factory=list)


class DailyReport(Entity):
    summary_md: str
    details_md: str


def create_daily_report(
    output: TFCITestOutput,
) -> DailyReport:
    raise NotImplementedError
