from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from enum import StrEnum

import humanize
from github.WorkflowJob import WorkflowJob
from model_lib import Entity, Event, utc_datetime
from pydantic import Field

logger = logging.getLogger(__name__)


class GoTestStatus(StrEnum):
    RUN = "RUN"
    PASS = "PASS"  # noqa: S105
    FAIL = "FAIL"
    SKIP = "SKIP"


class Classification(StrEnum):
    OUT_OF_CAPACITY = "OUT_OF_CAPACITY"
    # DANGLING_RESOURCES = "DANGLING_RESOURCES"
    # PERFORMANCE_REGRESSION = "PERFORMANCE_REGRESSION"
    FIRST_TIME_ERROR = "FIRST_TIME_ERROR"
    LEGIT_ERROR = "LEGIT_ERROR"
    PANIC = "PANIC"


class LineInfo(Event):
    number: int
    text: str


class GoTestRun(Entity):
    name: str
    status: GoTestStatus = GoTestStatus.RUN
    start_line: LineInfo
    ts: utc_datetime
    finish_ts: utc_datetime | None = None
    job: WorkflowJob
    test_step: int

    finish_line: LineInfo | None = None
    context_lines: list[str] = Field(default_factory=list)
    run_seconds: float | None = None

    classifications: set[Classification] = Field(default_factory=set)

    def finish_summary(self) -> str:
        finish_line = self.finish_line
        lines = [
            self.start_line.text if finish_line is None else finish_line.text,
            self.url,
        ]
        return "\n".join(lines + self.context_lines)

    @property
    def when(self) -> str:
        return humanize.naturaltime(self.ts)

    @property
    def runtime_human(self) -> str:
        if seconds := self.run_seconds:
            return humanize.naturaldelta(seconds)
        return "unknown"

    @property
    def context_lines_str(self) -> str:
        return "\n".join(self.context_lines)

    @property
    def url(self) -> str:
        line = self.finish_line or self.start_line
        return f"{self.job.html_url}#step:{self.test_step}:{line.number}"

    @property
    def is_failure(self) -> bool:
        return self.status == GoTestStatus.FAIL

    def add_line_match(self, match: LineMatch, line: str, line_number: int) -> None:
        self.run_seconds = match.run_seconds or self.run_seconds
        self.finish_line = LineInfo(number=line_number, text=line)
        self.status = match.status
        self.finish_ts = match.ts

    @classmethod
    def from_line_match(
        cls,
        match: LineMatch,
        line: str,
        line_number: int,
        job: WorkflowJob,
        test_step_nr: int,
    ) -> GoTestRun:
        start_line = LineInfo(number=line_number, text=line)
        return cls(
            name=match.name,
            status=match.status,
            ts=match.ts,
            run_seconds=match.run_seconds,
            start_line=start_line,
            job=job,
            test_step=test_step_nr,
        )


class LineMatch(Event):
    ts: utc_datetime
    status: GoTestStatus
    name: str
    run_seconds: float | None = None


_status_options = "|".join(list(GoTestStatus))
line_result = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z?)\s[-=]+\s"
    + r"(?P<status>%s):?\s+" % _status_options  # noqa: UP031
    + r"(?P<name>[\w_]+)"
    + r"\s*\(?(?P<run_seconds>[\d\.]+)?s?\)?"
)


def match_line(line: str) -> LineMatch | None:
    """
    2024-06-26T04:41:47.7209465Z === RUN   TestAccNetworkDSPrivateLinkEndpoint_basic
    2024-06-26T04:41:47.7228652Z --- PASS: TestAccNetworkRSPrivateLinkEndpointGCP_basic (424.50s)
    """
    if match := line_result.match(line):
        return LineMatch(**match.groupdict())
    return None


context_start_pattern = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z?)\s[-=]+\s" r"NAME\s+" r"(?P<name>[\w_]+)"
)


def context_start_match(line: str) -> str:
    if match := context_start_pattern.match(line):
        return match.groupdict()["name"]
    return ""


context_line_pattern = re.compile(
    r"(?P<ts>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z?)" r"\s{5}" r"(?P<indent>\s*)" r"(?P<relevant_line>.*)"
)


def extract_context(line: str) -> str:
    if match := context_line_pattern.match(line):
        match_vars = match.groupdict()
        return match_vars["indent"] + match_vars["relevant_line"].strip()
    return ""


def parse(test_lines: list[str], job: WorkflowJob, test_step_nr: int) -> Iterable[GoTestRun]:
    tests: dict[str, GoTestRun] = {}
    context_lines: list[str] = []
    current_context_test = ""
    for line_nr, line in enumerate(test_lines, start=0):  # possibly an extra line in the log files we download
        if current_context_test:
            if more_context := extract_context(line):
                context_lines.append(more_context)
                continue
            else:
                tests[current_context_test].context_lines.extend(context_lines)
                context_lines.clear()
                current_context_test = ""
        if new_context_test := context_start_match(line):
            current_context_test = new_context_test
            continue
        if line_match := match_line(line):
            if existing := tests.pop(line_match.name, None):
                existing.add_line_match(line_match, line, line_nr)
                yield existing
            else:
                tests[line_match.name] = GoTestRun.from_line_match(line_match, line, line_nr, job, test_step_nr)
    if tests:
        logger.warning(f"unfinished tests: {sorted(tests.keys())}")
