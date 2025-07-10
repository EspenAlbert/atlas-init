from __future__ import annotations

import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum
from functools import reduce, total_ordering
from pathlib import Path
import re
from typing import Callable, ClassVar, TypeVar

from ask_shell.rich_progress import new_task
from model_lib import Entity
from pydantic import Field, model_validator
from zero_3rdparty import datetime_utils, file_utils
from zero_3rdparty.iter_utils import group_by_once

from atlas_init.cli_tf.github_logs import summary_dir
from atlas_init.cli_tf.go_test_run import GoTestRun, GoTestStatus
from atlas_init.cli_tf.go_test_tf_error import (
    GoTestError,
    GoTestErrorClass,
    GoTestErrorClassification,
    details_short_description,
    parse_error_details,
)
from atlas_init.crud.mongo_dao import MongoDao, init_mongo_dao
from atlas_init.html_out.md_export import MonthlyReportPaths
from atlas_init.settings.env_vars import AtlasInitSettings

logger = logging.getLogger(__name__)
_COMPLETE_STATUSES = {GoTestStatus.PASS, GoTestStatus.FAIL}


@total_ordering
class GoTestSummary(Entity):
    name: str
    results: list[GoTestRun] = Field(default_factory=list)
    classifications: dict[str, GoTestErrorClassification] = Field(default_factory=dict)

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
            if not self.is_skipped:
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


def test_detail_md(summary: GoTestSummary, start_date: datetime, end_date: datetime) -> str:
    return "\n".join(
        [
            f"# {summary.name} Test Details",
            summary_line(summary.results),
            f"Success rate: {summary.success_rate_human}",
            "",
            *error_table(summary),
            "## Timeline",
            *timeline_lines(summary, start_date, end_date),
        ]
    )


def timeline_lines(summary: GoTestSummary, start_date: datetime, end_date: datetime) -> list[str]:
    lines = []
    one_day = timedelta(days=1)
    for active_date in datetime_utils.day_range(start_date.date(), (end_date + one_day).date(), one_day):
        active_tests = summary.select_tests(active_date)
        if not active_tests:
            lines.append(f"- {active_date:%Y-%m-%d}: MISSING")
            continue
        lines.append(f"- {active_date:%Y-%m-%d}")
        if len(active_tests) == 1:
            test = active_tests[0]
            if test.is_failure:
                lines.extend(_extract_error_lines(test, summary))
            else:
                lines[-1] += f" {format_test_oneline(test)}"
        if len(active_tests) > 1:
            for test in active_tests:
                error_lines = _extract_error_lines(test, summary)
                lines.extend(
                    [
                        f"  - {format_test_oneline(test)}",
                        *error_lines,
                    ]
                )
    return lines


def _error_header(test: GoTestRun) -> str:
    return f"Error {test.ts.isoformat('T', timespec='seconds')}"


def _extract_error_lines(test: GoTestRun, summary: GoTestSummary) -> list[str]:
    if not test.is_failure:
        return []
    error_classification = summary.classifications.get(test.id)
    classification_lines = [str(error_classification)] if error_classification else []
    details_lines = [details_short_description(error_classification.details)] if error_classification else []
    return [
        "",
        f"### {_error_header(test)}",
        *classification_lines,
        *details_lines,
        f"```\n{test.output_lines_str}\n```",
        "",
    ]


def failure_details(summary: GoTestSummary) -> list[str]:
    lines = ["## Failures"]
    for test in summary.results:
        if test.status == GoTestStatus.FAIL:
            lines.extend(
                (
                    f"### {test.when} {format_test_oneline(test)}",
                    test.finish_summary(),  # type: ignore
                    "",
                )
            )
    return lines


def error_table(summary: GoTestSummary) -> list[str]:
    error_rows: list[dict] = []
    for test in summary.results:
        if test.is_failure:
            anchor = header_to_markdown_link(_error_header(test))
            row = {
                "Date": f"[{test.ts.strftime('%Y-%m-%d %H:%M')}]({anchor})",
                "Env": test.env,
                "Runtime": f"{test.run_seconds:.2f}s",
            }
            error_rows.append(row)
            if error_cls := summary.classifications.get(test.id):
                row["Error Class"] = error_cls.error_class
                row["Details"] = details_short_description(error_cls.details)
            elif auto_class := GoTestErrorClass.auto_classification(test.output_lines_str):
                row["Error Class"] = auto_class
            if "Details" not in row:
                row["Details"] = details_short_description(parse_error_details(test))
    if not error_rows:
        return []
    headers = sorted(reduce(lambda x, y: x.union(y.keys()), error_rows, set()))
    return markdown_table_lines("Error Table", error_rows, headers, lambda row: [row.get(key, "") for key in headers])


def format_test_oneline(test: GoTestRun) -> str:
    if job_url := test.job_url:
        return f"[{test.status} {test.runtime_human}]({job_url})"
    return f"{test.status} {test.runtime_human}"  # type: ignore


def header_to_markdown_link(header: str) -> str:
    """
    Converts a markdown header to a markdown link anchor.
    Example:
        'Error 2025-05-23T00:28:50+00:00' -> '#error-2025-05-23t0028500000'
    """
    anchor = header.strip().lower()
    # Remove all characters except alphanumerics, spaces, and hyphens
    anchor = re.sub(r"[^a-z0-9 \-]", "", anchor)
    anchor = anchor.replace(" ", "-")
    return f"#{anchor}"


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
            f"  - [{fail_run.when} failed in {fail_run.runtime_human}]({fail_run.url})"  # type: ignore
            for fail_run in fail_tests
        )
        summary_fail_details.append(f"\n\n ## {fail_name} details:")
        summary_fail_details.extend(f"```\n{fail_run.finish_summary()}\n```" for fail_run in fail_tests)  # type: ignore
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
    envs = {run.env for run in runs if run.env}
    lines = [summary_line(runs)]
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


def run_statuses(runs: list[GoTestRun]) -> str:
    if counter := Counter([run.status for run in runs]):
        return " ".join(
            f"{cls}(x {count})" if count > 1 else cls
            for cls, count in sorted(counter.items(), key=lambda item: item[1], reverse=True)
        )
    return ""


def summary_line(runs: list[GoTestRun]):
    run_delta = GoTestRun.run_delta(runs)
    envs = {run.env for run in runs if run.env}
    pkg_test_names = {run.name_with_package for run in runs}
    envs_str = ", ".join(sorted(envs))
    branches = {run.branch for run in runs if run.branch}
    branches_str = (
        "from " + ", ".join(sorted(branches)) + " branches" if len(branches) > 1 else f"from {branches.pop()} branch"
    )
    return f"# Found {len(runs)} TestRuns in {envs_str} {run_delta} {branches_str}: {len(pkg_test_names)} unique tests, {run_statuses(runs)}"


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
    """Represent the CI Test Output for a day"""

    log_paths: list[Path] = Field(
        default_factory=list, description="Paths to the log files of the test runs analyzed by the run history."
    )
    found_tests: list[GoTestRun] = Field(default_factory=list, description="All tests for report day.")
    found_errors: list[GoTestError] = Field(default_factory=list, description="All errors for the report day.")
    classified_errors: list[GoTestErrorClassification] = Field(
        default_factory=list, description="Classified errors for the report day."
    )


class RunHistoryFilter(Entity):
    run_history_start: datetime
    run_history_end: datetime
    env_filter: list[str] = Field(default_factory=list)
    skip_branch_filter: bool = False


class MonthlyReportIn(Entity):
    name: str
    branch: str
    history_filter: RunHistoryFilter
    skip_columns: set[ErrorRowColumns] = Field(default_factory=set)
    skip_rows: list[Callable[[TestRow], bool]] = Field(default_factory=list)
    existing_details_md: dict[str, str] = Field(default_factory=dict)
    report_paths: MonthlyReportPaths

    @classmethod
    def skip_skipped(cls, test: TestRow) -> bool:
        return all(run.is_skipped for runs in test.last_env_runs.values() for run in runs)

    @classmethod
    def skip_if_no_failures(cls, test: TestRow) -> bool:
        return not any(run.is_failure for runs in test.last_env_runs.values() for run in runs)


class MonthlyReportOut(Entity):
    summary_md: str
    test_details_md: dict[str, str] = Field(default_factory=dict)


class ErrorRowColumns(StrEnum):
    GROUP_NAME = "Group with Package"
    TEST = "Test"
    ERROR_CLASS = "Error Class"
    DETAILS_SUMMARY = "Details Summary"
    PASS_RATE = "Pass Rate"  # nosec B105 # This is not a security issue, just a column name
    TIME_SINCE_PASS = "Time Since PASS"  # nosec B105 # This is not a security issue, just a column name

    __ENV_BASED__: ClassVar[list[str]] = [PASS_RATE, TIME_SINCE_PASS]

    @classmethod
    def column_names(cls, rows: list[TestRow], skip_columns: set[ErrorRowColumns]) -> list[str]:
        if not rows:
            return []
        envs = set()
        for row in rows:
            envs.update(row.last_env_runs.keys())
        columns: list[str] = [cls.GROUP_NAME, cls.TEST, cls.ERROR_CLASS, cls.DETAILS_SUMMARY]
        for env in sorted(envs):
            columns.extend(f"{env_col} ({env})" for env_col in cls.__ENV_BASED__ if env_col not in skip_columns)
        return [col for col in columns if col not in skip_columns]


@total_ordering
class TestRow(Entity):
    group_name: str
    package_url: str
    full_name: str
    test_name: str
    error_classes: list[GoTestErrorClass]
    details_summary: str
    last_env_runs: dict[str, list[GoTestRun]] = field(default_factory=dict)

    def __lt__(self, other) -> bool:
        if not isinstance(other, TestRow):
            raise TypeError
        return (self.group_name, self.test_name) < (other.group_name, other.test_name)

    @property
    def pass_rates(self) -> dict[str, float]:
        rates = {}
        for env, runs in self.last_env_runs.items():
            if not runs:
                continue
            total = len(runs)
            passed = sum(run.status == GoTestStatus.PASS for run in runs)
            rates[env] = passed / total if total > 0 else 0.0
        return rates

    @property
    def time_since_pass(self) -> dict[str, str]:
        time_since = {}
        for env, runs in self.last_env_runs.items():
            if not runs:
                time_since[env] = "never run"
                continue
            time_since[env] = next(
                (run.ts.strftime("%Y-%m-%d") for run in sorted(runs, reverse=True) if run.status == GoTestStatus.PASS),
                "never pass",
            )
        return time_since

    @property
    def error_classes_str(self) -> str:
        if counter := Counter(self.error_classes):
            return " ".join(
                f"{cls}(x {count})" if count > 1 else cls
                for cls, count in sorted(counter.items(), key=lambda item: item[1], reverse=True)
            )
        return "No error classes"

    def as_row(self, columns: list[str]) -> list[str]:
        values = []
        pass_rates = self.pass_rates
        time_since_pass = self.time_since_pass
        for col in columns:
            match col:
                case ErrorRowColumns.GROUP_NAME:
                    group_part = self.full_name.removesuffix(self.test_name).rstrip("/")
                    values.append(group_part or "Unknown Group")
                case ErrorRowColumns.TEST:
                    values.append(self.test_name)
                case ErrorRowColumns.ERROR_CLASS:
                    values.append(self.error_classes_str)
                case ErrorRowColumns.DETAILS_SUMMARY:
                    values.append(self.details_summary)
                case s if s.startswith(ErrorRowColumns.PASS_RATE):
                    env = s.split(" (")[-1].rstrip(")")
                    env_pass_rate = pass_rates.get(env, 0.0)
                    env_run_count = len(self.last_env_runs.get(env, []))
                    pass_rate_pct = f"{env_pass_rate:.2%} ({env_run_count} runs)" if env in pass_rates else "N/A"
                    if pass_rate_pct.startswith("100.00%"):
                        values.append("always")  # use always to avoid sorting errors, 100% showing before 2%
                    else:
                        values.append(pass_rate_pct)
                case s if s.startswith(ErrorRowColumns.TIME_SINCE_PASS):
                    env = s.split(" (")[-1].rstrip(")")
                    values.append(time_since_pass.get(env, "never passed"))
                case _:
                    logger.warning(f"Unknown column: {col}, skipping")
                    values.append("N/A")
        return values


def create_monthly_report(settings: AtlasInitSettings, event: MonthlyReportIn) -> MonthlyReportOut:
    with new_task(f"Monthly Report for {event.name} on {event.branch}"):
        test_rows, detail_files_md = asyncio.run(_collect_monthly_test_rows_and_summaries(settings, event))
        assert test_rows, "No error rows found for monthly report"
    columns = ErrorRowColumns.column_names(test_rows, event.skip_columns)
    skip_rows = (
        []
        if event.skip_rows == []
        else [
            "",
            "## Skip Test Filters",
            *[f"- {method.__name__}" for method in event.skip_rows],
            "",
        ]
    )
    summary_md = [
        f"# Monthly Report for {event.name} on {event.branch} from {event.history_filter.run_history_start:%Y-%m-%d} to {event.history_filter.run_history_end:%Y-%m-%d} Found {len(test_rows)} unique Tests",
        *skip_rows,
        *markdown_table_lines("Test Run Table", test_rows, columns, lambda row: row.as_row(columns)),
    ]
    return MonthlyReportOut(
        summary_md="\n".join(summary_md),
        test_details_md=detail_files_md,
    )


class DailyReportIn(Entity):
    report_date: datetime
    history_filter: RunHistoryFilter
    skip_columns: set[ErrorRowColumns] = Field(default_factory=set)
    row_modifier: Callable[[TestRow, dict[str, str]], dict[str, str]] | None = Field(
        default=None, description=f"Use the {ErrorRowColumns} to access column-->value mapping"
    )


class DailyReportOut(Entity):
    summary_md: str
    details_md: str


T = TypeVar("T")


def markdown_table_lines(
    header: str, rows: list[T], columns: list[str], row_to_line: Callable[[T], list[str]], *, header_level: int = 2
) -> list[str]:
    if not rows:
        return []
    return [
        f"{'#' * header_level} {header}",
        "",
        " | ".join(columns),
        " | ".join("---" for _ in columns),
        *(" | ".join(row_to_line(row)) for row in rows),
        "",
    ]


def create_daily_report(output: TFCITestOutput, settings: AtlasInitSettings, event: DailyReportIn) -> DailyReportOut:
    errors = output.found_errors
    error_classes = {cls.run_id: cls.error_class for cls in output.classified_errors}
    one_line_summary = summary_line(output.found_tests)

    with new_task("Daily Report"):
        with new_task("Collecting error rows") as task:
            failure_rows = asyncio.run(
                _collect_daily_error_rows(errors, error_classes, settings, event.history_filter, task)
            )
        if not failure_rows:
            return DailyReportOut(summary_md=f"🎉All tests passed\n{one_line_summary}", details_md="")
    columns = ErrorRowColumns.column_names(failure_rows, event.skip_columns)

    def as_md_row(row: TestRow) -> list[str]:
        if row_modifier := event.row_modifier:
            row_dict = dict(zip(columns, row.as_row(columns)))
            row_dict = row_modifier(row, row_dict)
            return [row_dict[col] for col in columns]
        return row.as_row(columns)

    summary_md = [
        f"# Daily Report on {event.report_date:%Y-%m-%d}",
        one_line_summary,
        "",
        *markdown_table_lines("Errors Table", failure_rows, columns, as_md_row),
    ]
    return DailyReportOut(summary_md="\n".join(summary_md), details_md="TODO")


async def _collect_daily_error_rows(
    errors: list[GoTestError],
    error_classes: dict[str, GoTestErrorClass],
    settings: AtlasInitSettings,
    event: RunHistoryFilter,
    task: new_task,
) -> list[TestRow]:
    error_rows: list[TestRow] = []
    dao = await init_mongo_dao(settings)
    for error in errors:
        test_run = error.run
        error_class = error_classes[error.run_id]
        summary = error.short_description
        error_row, _ = await _create_test_row(event, dao, test_run, error_class, summary)
        error_rows.append(error_row)
        task.update(advance=1)
    return sorted(error_rows)


async def _collect_monthly_test_rows_and_summaries(
    settings: AtlasInitSettings,
    event: MonthlyReportIn,
) -> tuple[list[TestRow], dict[str, str]]:
    dao = await init_mongo_dao(settings)
    branch = event.branch
    history_filter = event.history_filter
    summary_name = event.name
    skip_rows = event.skip_rows
    last_day_test_names = await dao.read_tf_tests_for_day(branch, history_filter.run_history_end)
    test_runs_by_name: dict[str, GoTestRun] = {run.full_name: run for run in last_day_test_names}
    test_rows = []
    detail_files_md: dict[str, str] = {}
    with new_task("Collecting monthly error rows", total=len(last_day_test_names)) as task:
        for name_with_group, test_run in test_runs_by_name.items():
            test_row, runs = await _create_test_row(
                history_filter,
                dao,
                test_run,
            )
            if any(skip(test_row) for skip in skip_rows):
                continue
            test_rows.append(test_row)
            run_ids = [run.id for run in runs]
            classifications = await dao.read_error_classifications(run_ids)
            test_row.error_classes = [cls.error_class for cls in classifications.values()]
            test_row.details_summary = (
                f"[{run_statuses(runs)}]({settings.github_ci_summary_details_rel_path(summary_name, name_with_group)})"
            )
            if name_with_group not in event.existing_details_md:
                summary = GoTestSummary(name=name_with_group, results=runs, classifications=classifications)
                detail_files_md[name_with_group] = test_detail_md(
                    summary, history_filter.run_history_start, history_filter.run_history_end
                )
            task.update(advance=1)
    return sorted(test_rows), detail_files_md


async def _create_test_row(
    history_filter: RunHistoryFilter,
    dao: MongoDao,
    test_run: GoTestRun,
    error_class: GoTestErrorClass | None = None,
    summary: str = "",
) -> tuple[TestRow, list[GoTestRun]]:
    package_url = test_run.package_url
    group_name = test_run.group_name
    package_url = test_run.package_url or ""
    branch = test_run.branch
    branch_filter = []
    test_name = test_run.name
    if branch and not history_filter.skip_branch_filter:
        branch_filter.append(branch)
    run_history = await dao.read_run_history(
        test_name=test_name,
        package_url=package_url,
        group_name=group_name,
        start_date=history_filter.run_history_start,
        end_date=history_filter.run_history_end,
        envs=history_filter.env_filter,
        branches=branch_filter,
    )
    last_env_runs = group_by_once(run_history, key=lambda run: run.env or "unknown-env")
    error_classes = [error_class] if error_class else []
    return TestRow(
        full_name=test_run.full_name,
        group_name=group_name,
        package_url=package_url,
        test_name=test_name,
        error_classes=error_classes,
        details_summary=summary,
        last_env_runs=last_env_runs,
    ), run_history
