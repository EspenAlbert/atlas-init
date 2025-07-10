from __future__ import annotations

import logging
import re
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from functools import total_ordering
from pathlib import Path
from typing import NamedTuple, TypeAlias

import humanize
from model_lib import Entity, utc_datetime, utc_datetime_ms
from pydantic import Field, model_validator
from zero_3rdparty.datetime_utils import utc_now

from atlas_init.repos.path import go_package_prefix

logger = logging.getLogger(__name__)


class GoTestStatus(StrEnum):
    RUN = "RUN"
    PAUSE = "PAUSE"
    NAME = "NAME"
    PASS = "PASS"  # noqa: S105 #nosec
    FAIL = "FAIL"
    SKIP = "SKIP"
    CONT = "CONT"
    TIMEOUT = "TIMEOUT"
    PKG_OK = "ok"

    @classmethod
    def is_running(cls, status: GoTestStatus) -> bool:
        return status in {cls.RUN, cls.PAUSE, cls.NAME, cls.CONT}

    @classmethod
    def is_running_but_not_paused(cls, status: GoTestStatus) -> bool:
        return status != cls.PAUSE and cls.is_running(status)

    @classmethod
    def is_pass_or_fail(cls, status: GoTestStatus) -> bool:
        return status in {cls.PASS, cls.FAIL, cls.TIMEOUT}  # TIMEOUT is considered a failure in this context


class GoTestContextStep(Entity):
    name: str


class GoTestContext(Entity):
    """Abstraction on WorkflowJob to also support local runs"""

    name: str
    created_at: utc_datetime = Field(default_factory=utc_now)
    steps: list[GoTestContextStep] = Field(default_factory=list)
    html_url: str = "http://localhost"

    @classmethod
    def from_local_run(cls, name: str, steps: list[GoTestContextStep]) -> GoTestContext:
        raise NotImplementedError
        # return cls(name=name, steps=steps)


def extract_group_name(log_path: Path | None) -> str:
    """
    >>> extract_group_name(
    ...     Path(
    ...         "40216340925_tests-1.11.x-latest_tests-1.11.x-latest-false_search_deployment.txt"
    ...     )
    ... )
    'search_deployment'
    >>> extract_group_name(None)
    ''
    """
    if log_path is None:
        return ""
    if "-" not in log_path.name:
        return ""
    last_part = log_path.stem.split("-")[-1]
    return "_".join(last_part.split("_")[1:]) if "_" in last_part else last_part


def parse_tests(
    log_lines: list[str],
) -> list[GoTestRun]:
    context = ParseContext()
    parser = wait_for_relvant_line
    for line in log_lines:
        parser = parser(line, context)
        context.last_lines.append(line)
    result = context.finish_parsing()
    return result.tests


class GoTestRuntimeStats(NamedTuple):
    slowest_seconds: float
    average_seconds: float | None
    name_with_package: str
    runs: list[GoTestRun]

    @property
    def slowest_duration(self) -> str:
        return humanize.naturaldelta(self.slowest_seconds)

    @property
    def average_duration(self) -> str:
        if self.average_seconds is None:
            return ""
        return humanize.naturaldelta(self.average_seconds)


class GoTestLastPassStat(NamedTuple):
    pass_ts: utc_datetime
    name_with_package: str
    pass_when: str
    last_pass: GoTestRun


@total_ordering
class GoTestRun(Entity):
    name: str
    status: GoTestStatus = GoTestStatus.RUN
    ts: utc_datetime_ms
    output_lines: list[str] = Field(default_factory=list)
    finish_ts: utc_datetime_ms | None = None
    run_seconds: float | None = Field(default=None, init=False)

    package_url: str | None = Field(default=None, init=False)

    log_path: Path | None = Field(default=None, init=False)
    env: str | None = Field(default=None, init=False)
    branch: str | None = Field(default=None, init=False)
    resources: list[str] = Field(default_factory=list, init=False)
    job_url: str | None = Field(default=None, init=False)

    def __lt__(self, other) -> bool:
        if not isinstance(other, GoTestRun):
            raise TypeError
        return (self.ts, self.name) < (other.ts, other.name)

    @property
    def id(self) -> str:
        return f"{self.ts.isoformat()}-{self.name}"

    @property
    def when(self) -> str:
        return humanize.naturaltime(self.ts)

    @property
    def runtime_human(self) -> str:
        if seconds := self.run_seconds:
            return humanize.naturaldelta(seconds)
        return "unknown"

    @property
    def output_lines_str(self) -> str:
        return "\n".join(self.output_lines)

    @property
    def is_failure(self) -> bool:
        return self.status in {GoTestStatus.FAIL, GoTestStatus.TIMEOUT}

    @property
    def is_skipped(self) -> bool:
        return self.status == GoTestStatus.SKIP

    @property
    def is_pass(self) -> bool:
        return self.status == GoTestStatus.PASS

    @property
    def group_name(self) -> str:
        return extract_group_name(self.log_path)

    def package_rel_path(self, repo_path: Path) -> str:
        if url := self.package_url:
            prefix = go_package_prefix(repo_path)
            return url.removeprefix(prefix).rstrip("/")
        return ""

    @property
    def name_with_package(self) -> str:
        if self.package_url:
            return f"{self.package_url.split('/')[-1]}/{self.name}"
        return self.name

    @property
    def full_name(self) -> str:
        if self.package_url and self.group_name:
            return f"{self.group_name}/{self.package_url.split('/')[-1]}/{self.name}"
        if self.group_name:
            return f"{self.group_name}/{self.name}"
        return self.name_with_package

    @classmethod
    def group_by_name_package(cls, tests: list[GoTestRun]) -> dict[str, list[GoTestRun]]:
        grouped = defaultdict(list)
        for test in tests:
            grouped[test.name_with_package].append(test)
        return grouped

    @classmethod
    def pass_rate_or_skip_reason(cls, tests: list[GoTestRun], *, include_single_run: bool = False) -> tuple[float, str]:
        if not tests:
            return 0.0, "No tests"
        fail_count = sum(test.is_pass for test in tests)
        total_count = sum(GoTestStatus.is_pass_or_fail(test.status) for test in tests)
        if not include_single_run and total_count == 1:
            return 0.0, "Only one test and include_single_run is False"
        if total_count == 0:
            return 0.0, "No pass or fail tests"
        return fail_count / total_count, ""

    @classmethod
    def last_pass(cls, tests: list[GoTestRun]) -> str:
        last_pass = max((test for test in tests if test.is_pass), default=None)
        return last_pass.when if last_pass else ""

    @classmethod
    def last_pass_stats(cls, tests: list[GoTestRun], *, max_tests: int = 10) -> list[GoTestLastPassStat]:
        """Returns"""
        pass_stats: list[GoTestLastPassStat] = []
        for name_with_package, name_tests in cls.group_by_name_package(tests).items():
            has_passes = bool(sum(test.is_pass for test in name_tests))
            if not has_passes:
                continue
            has_failures = bool(sum(test.is_failure for test in name_tests))
            if not has_failures:
                continue
            last_pass_test = max((test for test in name_tests if test.is_pass))
            finish_ts = last_pass_test.finish_ts
            assert finish_ts is not None, f"last_pass {last_pass_test} has no finish_ts"
            pass_stats.append(GoTestLastPassStat(finish_ts, name_with_package, last_pass_test.when, last_pass_test))
        return sorted(pass_stats)[:max_tests]

    @classmethod
    def lowest_pass_rate(
        cls, tests: list[GoTestRun], *, max_tests: int = 10, include_single_run: bool = False
    ) -> list[tuple[float, str, list[GoTestRun]]]:
        tests_with_pass_rates = []
        grouped = cls.group_by_name_package(tests)
        for name, tests in grouped.items():
            pass_rate, skip_reason = cls.pass_rate_or_skip_reason(tests, include_single_run=include_single_run)
            if skip_reason or pass_rate == 1.0:
                continue
            tests_with_pass_rates.append((pass_rate, name, tests))
        return sorted(tests_with_pass_rates)[:max_tests]

    @classmethod
    def run_delta(cls, tests: list[GoTestRun]) -> str:
        if not tests:
            return "No tests"
        run_dates = {run.ts.date() for run in tests}
        if len(run_dates) == 1:
            return f"on {run_dates.pop().strftime('%Y-%m-%d')}"
        return f"from {min(run_dates).strftime('%Y-%m-%d')} to {max(run_dates).strftime('%Y-%m-%d')}"

    @classmethod
    def slowest_tests(cls, tests: list[GoTestRun], *, max_tests: int = 10) -> list[GoTestRuntimeStats]:
        def run_time(test: GoTestRun) -> float:
            return test.run_seconds or 0.0

        slowest_tests = sorted(tests, key=run_time, reverse=True)
        stats = []
        grouped_by_name = cls.group_by_name_package(slowest_tests)
        for slow_test in slowest_tests:
            if slow_test.name_with_package not in grouped_by_name:
                continue  # already processed
            runs = grouped_by_name.pop(slow_test.name_with_package)
            slowest_seconds = max(run_time(test) for test in runs)
            if slowest_seconds < 0.1:  # ignore tests less than 0.1 seconds
                return stats
            average_seconds = sum(run_time(test) for test in runs) / len(runs) if len(runs) > 1 else None
            stats.append(
                GoTestRuntimeStats(
                    slowest_seconds=slowest_seconds,
                    average_seconds=average_seconds,
                    name_with_package=slow_test.name_with_package,
                    runs=runs,
                )
            )
            if len(stats) >= max_tests:
                return stats
        return stats


class ParseResult(Entity):
    tests: list[GoTestRun] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_all_tests_completed(self) -> ParseResult:
        if incomplete_tests := [
            f"{test.name}-{test.status}" for test in self.tests if GoTestStatus.is_running(test.status)
        ]:
            raise ValueError(f"some tests are not completed: {incomplete_tests}")
        if no_package_tests := [(test.name, test.log_path) for test in self.tests if test.package_url is None]:
            raise ValueError(f"some tests do not have package name: {no_package_tests}")
        test_names = {test.name for test in self.tests}
        test_group_names = {name.split("/")[0] for name in test_names if "/" in name}
        self.tests = [test for test in self.tests if test.name not in test_group_names]
        return self


@dataclass
class ParseContext:
    tests: list[GoTestRun] = field(default_factory=list)

    current_output: list[str] = field(default_factory=list, init=False)
    current_test_name: str = ""  # used for debugging and breakpoints
    last_lines: deque = field(default_factory=lambda: deque(maxlen=10), init=False)

    def add_output_line(self, line: str) -> None:
        if is_blank_line(line) and self.current_output and is_blank_line(self.current_output[-1]):
            return  # avoid two blank lines in a row
        self._add_line(line)

    def _add_line(self, line: str) -> None:
        logger.debug(f"adding line to {self.current_test_name}: {line}")
        self.current_output.append(line)

    def start_test(self, test_name: str, start_line: str, ts: str) -> None:
        run = GoTestRun(name=test_name, ts=ts)  # type: ignore
        self.tests.append(run)
        self.continue_test(test_name, start_line)

    def continue_test(self, test_name: str, line: str) -> None:
        test = self.find_unfinished_test(test_name)
        self.current_output = test.output_lines
        self.current_test_name = test_name
        self._add_line(line)

    def find_unfinished_test(self, test_name: str) -> GoTestRun:
        test = next(
            (test for test in self.tests if test.name == test_name and GoTestStatus.is_running(test.status)),
            None,
        )
        assert test is not None, f"test {test_name} not found in context"
        return test

    def set_package(self, pkg_name: str) -> None:
        for test in self.tests:
            if test.package_url is None:
                test.package_url = pkg_name

    def finish_test(
        self,
        test_name: str,
        status: GoTestStatus,
        ts: str,
        end_line: str,
        run_seconds: float | None,
        extra_lines: list[str] | None = None,
    ) -> None:
        test = self.find_unfinished_test(test_name)
        test.status = status
        test.finish_ts = datetime.fromisoformat(ts)
        if extra_lines:
            test.output_lines.extend(extra_lines)
        test.output_lines.append(end_line)
        test.run_seconds = run_seconds

    def finish_parsing(self) -> ParseResult:
        return ParseResult(tests=self.tests)


LineParserT: TypeAlias = Callable[[str, ParseContext], "LineParserT"]


def ts_pattern(name: str) -> str:
    return r"(?P<%s>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z?)\s*" % name


blank_pattern = re.compile(ts_pattern("ts") + r"$", re.MULTILINE)


def is_blank_line(line: str) -> bool:
    return blank_pattern.match(line) is not None


_one_or_more_digit_or_star_pattern = r"(\d|\*)+"  # due to Github secrets, some digits can be replaced with "*"
runtime_pattern_no_parenthesis = (
    rf"(?P<runtime>{_one_or_more_digit_or_star_pattern}\.{_one_or_more_digit_or_star_pattern})s"
)
runtime_pattern = rf"\({runtime_pattern_no_parenthesis}\)"


ignore_line_pattern = [
    re.compile(ts_pattern("ts") + r"\s" + ts_pattern("ts2")),
    # 2025-04-29T00:44:02.9968072Z   error=
    # 2025-04-29T00:44:02.9968279Z   | exit status 1
    re.compile(ts_pattern("ts") + r"error=\s*$", re.MULTILINE),
    re.compile(ts_pattern("ts") + r"\|"),
]

status_patterns = [
    (GoTestStatus.RUN, re.compile(ts_pattern("ts") + r"=== RUN\s+(?P<name>\S+)")),
    (GoTestStatus.PAUSE, re.compile(ts_pattern("ts") + r"=== PAUSE\s+(?P<name>\S+)")),
    (GoTestStatus.NAME, re.compile(ts_pattern("ts") + r"=== NAME\s+(?P<name>\S+)")),
    (GoTestStatus.CONT, re.compile(ts_pattern("ts") + r"=== CONT\s+(?P<name>\S+)")),
    (
        GoTestStatus.PASS,
        re.compile(ts_pattern("ts") + r"--- PASS: (?P<name>\S+)\s+" + runtime_pattern),
    ),
    (
        GoTestStatus.FAIL,
        re.compile(ts_pattern("ts") + r"--- FAIL: (?P<name>\S+)\s" + runtime_pattern),
    ),
    (
        GoTestStatus.SKIP,
        re.compile(ts_pattern("ts") + r"--- SKIP: (?P<name>\S+)\s+" + runtime_pattern),
    ),
    (
        # 2025-06-06T05:30:18.9060127Z 		TestAccClusterAdvancedCluster_replicaSetAWSProvider (4h28m7s)
        GoTestStatus.TIMEOUT,
        re.compile(ts_pattern("ts") + r"\s+(?P<name>\S+)\s\((?P<hours>\d+)?h?(?P<minutes>\d+)?m(?P<seconds>\d+)?s\)"),
    ),
]
package_patterns = [
    (
        GoTestStatus.FAIL,
        re.compile(ts_pattern("ts") + r"FAIL\s+(?P<package_url>\S+)\s+" + runtime_pattern_no_parenthesis),
    ),
    (
        GoTestStatus.FAIL,
        re.compile(ts_pattern("ts") + r"FAIL\s+(?P<package_url>\S+)\s+\(cached\)"),
    ),
    (
        GoTestStatus.PKG_OK,
        re.compile(ts_pattern("ts") + r"ok\s+(?P<package_url>\S+)\s+" + runtime_pattern_no_parenthesis),
    ),
    (
        GoTestStatus.PKG_OK,
        re.compile(ts_pattern("ts") + r"ok\s+(?P<package_url>\S+)\s+\(cached\)"),
    ),
]


def line_match_status_pattern(
    line: str,
    context: ParseContext,
) -> GoTestStatus | None:
    for status, pattern in status_patterns:
        if pattern_match := pattern.match(line):
            test_name = pattern_match.group("name")
            assert test_name, f"test name not found in line: {line} when pattern matched {pattern}"
            ts = pattern_match.group("ts")
            assert ts, f"timestamp not found in line: {line} when pattern matched {pattern}"
            match status:
                case GoTestStatus.RUN:
                    context.start_test(test_name, line, ts)
                case GoTestStatus.NAME | GoTestStatus.CONT:
                    context.continue_test(test_name, line)
                case GoTestStatus.PAUSE:
                    return status  # do nothing
                case GoTestStatus.TIMEOUT:
                    hours = pattern_match.group("hours")
                    minutes = pattern_match.group("minutes")
                    seconds = pattern_match.group("seconds")
                    run_seconds = (
                        (int(hours) * 3600 if hours else 0)
                        + (int(minutes) * 60 if minutes else 0)
                        + (int(seconds) if seconds else 0)
                    )
                    last_two_lines = list(context.last_lines)[-2:]
                    context.finish_test(test_name, status, ts, line, run_seconds, extra_lines=last_two_lines)
                case GoTestStatus.PASS | GoTestStatus.FAIL | GoTestStatus.SKIP:
                    run_time = pattern_match.group("runtime")
                    assert run_time, (
                        f"runtime not found in line with status={status}: {line} when pattern matched {pattern}"
                    )
                    seconds, milliseconds = run_time.split(".")
                    if "*" in seconds:
                        run_seconds = None
                    else:
                        run_seconds = int(seconds) + int(milliseconds.replace("*", "0")) / 1000
                    context.finish_test(test_name, status, ts, line, run_seconds)
            return status
    for pkg_status, pattern in package_patterns:
        if pattern_match := pattern.match(line):
            pkg_name = pattern_match.group("package_url")
            assert pkg_name, f"package_url not found in line: {line} when pattern matched {pattern}"
            context.set_package(pkg_name)
            return pkg_status
    return None


def wait_for_relvant_line(
    line: str,
    context: ParseContext,
) -> LineParserT:
    status = line_match_status_pattern(line, context)
    if status and GoTestStatus.is_running_but_not_paused(status):
        return add_output_line
    return wait_for_relvant_line


def add_output_line(
    line: str,
    context: ParseContext,
) -> LineParserT:
    for pattern in ignore_line_pattern:
        if pattern.match(line):
            return add_output_line
    status: GoTestStatus | None = line_match_status_pattern(line, context)
    if status is None:
        context.add_output_line(line)
        return add_output_line
    if status and GoTestStatus.is_running_but_not_paused(status):
        return add_output_line
    return wait_for_relvant_line
