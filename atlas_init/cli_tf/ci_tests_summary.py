from __future__ import annotations
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
import logging
import os
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
import re
from typing import TypeAlias

import humanize
from model_lib import Entity, Event, utc_datetime
from pydantic import Field, model_validator
from pydantic_core import Url
import typer
from zero_3rdparty.datetime_utils import utc_now

from atlas_init.cli_helper.run import add_to_clipboard, run_command_receive_result
from atlas_init.cli_tf.github_logs import (
    GH_TOKEN_ENV_NAME,
    download_job_safely,
    find_test_runs,
    include_filestems,
    include_test_jobs,
    tf_repo,
)
from atlas_init.cli_tf.go_test_run import GoTestRun, GoTestStatus, extract_group_name
from atlas_init.cli_tf.go_test_summary import (
    create_detailed_summary,
    create_short_summary,
)
from atlas_init.repos.path import Repo, current_repo_path
from atlas_init.settings.env_vars import AtlasInitSettings

logger = logging.getLogger(__name__)


def ci_tests(
    test_group_name: str = typer.Option("", "-g"),
    max_days_ago: int = typer.Option(1, "-d", "--days"),
    branch: str = typer.Option("master", "-b", "--branch"),
    workflow_file_stems: str = typer.Option("test-suite,terraform-compatibility-matrix", "-w", "--workflow"),
    only_last_workflow: bool = typer.Option(False, "-l", "--last"),
    names: str = typer.Option(
        "",
        "-n",
        "--test-names",
        help="comma separated list of test names to filter, e.g., TestAccCloudProviderAccessAuthorizationAzure_basic,TestAccBackupSnapshotExportBucket_basicAzure",
    ),
    summary_name: str = typer.Option(
        "",
        "-s",
        "--summary",
        help="the name of the summary directory to store detailed test results",
    ),
):  # sourcery skip: use-named-expression
    names_set: set[str] = set()
    if names:
        names_set.update(names.split(","))
        logger.info(f"filtering tests by names: {names_set}")
    repo_path = current_repo_path(Repo.TF)
    token = run_command_receive_result("gh auth token", cwd=repo_path, logger=logger)
    os.environ[GH_TOKEN_ENV_NAME] = token
    end_test_date = utc_now()
    start_test_date = end_test_date - timedelta(days=max_days_ago)
    job_runs = find_test_runs(
        start_test_date,
        include_job=include_test_jobs(test_group_name),
        branch=branch,
        include_workflow=include_filestems(set(workflow_file_stems.split(","))),
    )
    test_results: dict[str, list[GoTestRun]] = defaultdict(list)
    workflow_ids = set()
    for key in sorted(job_runs.keys(), reverse=True):
        workflow_id, job_id = key
        workflow_ids.add(workflow_id)
        if only_last_workflow and len(workflow_ids) > 1:
            logger.info("only showing last workflow")
            break
        runs = job_runs[key]
        if not runs:
            logger.warning(f"no go tests for job_id={job_id}")
            continue
        for run in runs:
            test_name = run.name
            if names_set and test_name not in names_set:
                continue
            test_results[test_name].append(run)

    if summary_name:
        summary = create_detailed_summary(summary_name, end_test_date, start_test_date, test_results, names_set)
    else:
        failing_names = [name for name, name_runs in test_results.items() if all(run.is_failure for run in name_runs)]
        if not failing_names:
            logger.info("ALL TESTS PASSED! ✅")
            return
        summary = create_short_summary(test_results, failing_names)
    summary_str = "\n".join(summary)
    add_to_clipboard(summary_str, logger)
    logger.info(summary_str)


class DownloadJobRunsInput(Event):
    branch: str = "master"
    run_date: date
    worker_count: int = 10
    max_wait_seconds: int = 300


class DownloadJobRunsOutput(Event):
    job_download_timeouts: int = 0
    job_download_empty: int = 0
    job_download_errors: int = 0
    log_paths: list[Path] = Field(default_factory=list)


def created_on_day(create: date) -> str:
    date_fmt = year_month_day(create)
    return f"{date_fmt}T00:00:00Z..{date_fmt}T23:59:59Z"


def year_month_day(create: date) -> str:
    return create.strftime("%Y-%m-%d")


_TEST_STEMS = {
    "test-suite",
    "terraform-compatibility-matrix",
    "acceptance-tests",
}


def download_gh_job_logs(settings: AtlasInitSettings, event: DownloadJobRunsInput) -> DownloadJobRunsOutput:
    repository = tf_repo()
    branch = event.branch
    is_test_job = include_test_jobs()
    futures: list[Future[Path | None]] = []
    run_date = event.run_date
    out = DownloadJobRunsOutput()
    with ThreadPoolExecutor(max_workers=event.worker_count) as pool:
        for workflow in repository.get_workflow_runs(
            created=created_on_day(run_date),
            branch=branch,  # type: ignore
        ):
            workflow_stem = Path(workflow.path).stem
            if workflow_stem not in _TEST_STEMS:
                continue
            workflow_dir = (
                settings.github_ci_run_logs / branch / year_month_day(run_date) / f"{workflow.id}_{workflow_stem}"
            )
            if workflow_dir.exists():
                logger.info(f"skipping existing workflow dir: {workflow_dir}")
                continue
            futures.extend(
                pool.submit(download_job_safely, workflow_dir, job) for job in workflow.jobs("all") if is_test_job(job)
            )
        done, not_done = wait(futures, timeout=event.max_wait_seconds)
        out.job_download_timeouts = len(not_done)
        for future in done:
            try:
                if log_path := future.result():
                    out.log_paths.append(log_path)
                else:
                    out.job_download_empty += 1
            except Exception as e:
                logger.error(f"failed to download job logs: {e}")
                out.job_download_errors += 1
    return out


class ParseJobLogsInput(Event):
    settings: AtlasInitSettings
    log_paths: list[Path]
    resource_name_resolver: Callable[[str], str]


class ParseJobLogsOutput(Event):
    resource_runs: dict[str, list[GoTestSimple]] = Field(default_factory=lambda: defaultdict(list))
    failure_runs: list[GoTestSimple] = Field(default_factory=list)


def parse_job_logs(
    event: ParseJobLogsInput,
) -> ParseJobLogsOutput:
    out = ParseJobLogsOutput()
    for log_path in event.log_paths:
        log_text = log_path.read_text()
        env = find_env_of_mongodb_base_url(log_text)
        result = parse_tests(log_text.splitlines())
        for test in result:
            test.log_path = log_path
            test.env = env or "unknown"
            # todo: set url, branch from the logs_path
            resource_name = event.resource_name_resolver(test.name)
            assert resource_name, f"resource name not found for test: {test.name}"
            out.resource_runs[resource_name].append(test)
            if test.is_failure:
                out.failure_runs.append(test)
    return out


def find_env_of_mongodb_base_url(log_text: str) -> str:
    for match in re.finditer(r"MONGODB_ATLAS_BASE_URL: (.*)$", log_text, re.MULTILINE):
        full_url = match.group(1)
        parsed = BaseURLEnvironment(url=Url(full_url))
        return parsed.env
    return ""


class BaseURLEnvironment(Entity):
    """
    >>> BaseURLEnvironment(url="https://cloud-dev.mongodb.com/").env
    'dev'
    """

    url: Url
    env: str = ""

    @model_validator(mode="after")
    def set_env(self) -> BaseURLEnvironment:
        host = self.url.host
        assert host, f"host not found in url: {self.url}"
        cloud_env = host.split(".")[0]
        self.env = cloud_env.removeprefix("cloud-")
        return self


def parse_tests(
    log_lines: list[str],
) -> list[GoTestSimple]:
    context = ParseContext()
    parser = wait_for_relvant_line
    for line in log_lines:
        parser = parser(line, context)
    result = context.finish_parsing()
    return result.tests


class GoTestSimple(Entity):
    name: str
    status: GoTestStatus = GoTestStatus.RUN
    ts: utc_datetime
    finish_ts: utc_datetime | None = None
    output_lines: list[str] = Field(default_factory=list)

    log_path: Path | None = None
    env: str | None = None
    branch: str | None = None
    run_seconds: float | None = None

    def __lt__(self, other) -> bool:
        if not isinstance(other, GoTestRun):
            raise TypeError
        return (self.ts, self.name) < (other.ts, other.name)

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
        return self.status == GoTestStatus.FAIL

    @property
    def is_pass(self) -> bool:
        return self.status == GoTestStatus.PASS

    @property
    def group_name(self) -> str:
        return extract_group_name(self.log_path)


class ParseResult(Event):
    tests: list[GoTestSimple] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_all_tests_completed(self) -> ParseResult:
        incomplete_tests = []
        incomplete_tests.extend(test for test in self.tests if test.finish_ts is None)
        if incomplete_tests:
            raise ValueError(f"some tests are not completed: {incomplete_tests}")
        return self


@dataclass
class ParseContext:
    tests: dict[str, GoTestSimple] = field(default_factory=dict)

    current_output: list[str] = field(default_factory=list, init=False)

    def add_output_line(self, line: str) -> None:
        self.current_output.append(line)

    def start_test(self, test_name: str, start_line: str, ts: str) -> None:
        run = GoTestSimple(name=test_name, output_lines=[start_line], ts=ts)  # type: ignore
        self.tests[test_name] = run
        self.continue_test(test_name)

    def continue_test(self, test_name: str) -> None:
        test = self.tests.get(test_name)
        assert test is not None, f"test {test_name} not found in context"
        self.current_output = test.output_lines

    def finish_test(self, test_name: str, status: GoTestStatus, ts: str, end_line: str) -> None:
        test = self.tests.get(test_name)
        assert test is not None, f"test {test_name} not found in context"
        test.status = status
        test.finish_ts = datetime.fromisoformat(ts)
        test.output_lines.append(end_line)

    def finish_parsing(self) -> ParseResult:
        return ParseResult(tests=list(self.tests.values()))


LineParserT: TypeAlias = Callable[[str, ParseContext], "LineParserT"]


def ts_pattern(name: str) -> str:
    return r"(?P<%s>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+Z?)\s*" % name


runtime_pattern = r"\((?P<runtime>\d+\.\d+s)\)"


ignore_line_pattern = [re.compile(ts_pattern("ts") + r"\s" + ts_pattern("ts2"))]

status_patterns = [
    (GoTestStatus.RUN, re.compile(ts_pattern("ts") + r"=== RUN\s+(?P<name>\S+)")),
    (GoTestStatus.PAUSE, re.compile(ts_pattern("ts") + r"=== PAUSE\s+(?P<name>[\S+]+)")),
    (GoTestStatus.NAME, re.compile(ts_pattern("ts") + r"=== NAME\s+(?P<name>[\S+]+)")),
    (GoTestStatus.PASS, re.compile(ts_pattern("ts") + r"--- PASS: (?P<name>[\S+]+)\s+" + runtime_pattern)),
    (GoTestStatus.FAIL, re.compile(ts_pattern("ts") + r"--- FAIL: (?P<name>[\S+]+)\s" + runtime_pattern)),
    (GoTestStatus.SKIP, re.compile(ts_pattern("ts") + r"--- SKIP: (?P<name>[\S+]+)\s+" + runtime_pattern)),
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
                case GoTestStatus.NAME:
                    context.continue_test(test_name)
                case GoTestStatus.PAUSE:
                    return status  # do nothing
                case GoTestStatus.PASS:
                    context.finish_test(test_name, status, ts, line)
                case GoTestStatus.FAIL:
                    context.finish_test(test_name, status, ts, line)
                case GoTestStatus.SKIP:
                    context.finish_test(test_name, status, ts, line)
            return status
    return None


def wait_for_relvant_line(
    line: str,
    context: ParseContext,
) -> LineParserT:
    status = line_match_status_pattern(line, context)
    if status in {GoTestStatus.RUN, GoTestStatus.NAME}:
        return add_output_line
    return wait_for_relvant_line


def add_output_line(
    line: str,
    context: ParseContext,
) -> LineParserT:
    for pattern in ignore_line_pattern:
        if pattern.match(line):
            return wait_for_relvant_line(line, context)
    status = line_match_status_pattern(line, context)
    if status is None:
        context.add_output_line(line)
        return add_output_line
    if status in {GoTestStatus.RUN, GoTestStatus.NAME}:
        return add_output_line
    return wait_for_relvant_line
