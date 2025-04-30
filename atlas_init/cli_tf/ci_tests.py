from __future__ import annotations

import logging
import os
import re
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import date, timedelta
from pathlib import Path

import typer
from model_lib import Entity, Event
from pydantic import Field, model_validator
from pydantic_core import Url
from zero_3rdparty import str_utils
from zero_3rdparty.datetime_utils import utc_now

from atlas_init.cli_helper.run import run_command_receive_result
from atlas_init.cli_tf.github_logs import (
    GH_TOKEN_ENV_NAME,
    download_job_safely,
    is_test_job,
    tf_repo,
)
from atlas_init.cli_tf.go_test_run import GoTestRun, GoTestStatus, parse_tests
from atlas_init.cli_tf.go_test_summary import create_test_report
from atlas_init.cli_tf.go_test_tf_error import (
    DetailsInfo,
    GoTestError,
    GoTestErrorClass,
    parse_error_details,
)
from atlas_init.cli_tf.mock_tf_log import resolve_admin_api_path
from atlas_init.crud.tf_resource import (
    TFErrors,
    TFResources,
    read_tf_error_by_run,
    read_tf_errors,
    read_tf_resources,
    store_or_update_tf_errors,
    store_tf_test_runs,
)
from atlas_init.repos.go_sdk import ApiSpecPaths, parse_api_spec_paths
from atlas_init.repos.path import Repo, current_repo_path
from atlas_init.settings.env_vars import AtlasInitSettings, init_settings
from atlas_init.settings.interactive2 import confirm, select_list

logger = logging.getLogger(__name__)


class TFCITestInput(Event):
    settings: AtlasInitSettings = Field(default_factory=init_settings)
    repo_path: Path = Field(default_factory=lambda: current_repo_path(Repo.TF))
    test_group_name: str = ""
    max_days_ago: int = 1
    branch: str = "master"
    workflow_file_stems: set[str] = Field(default_factory=lambda: set(_TEST_STEMS))
    names: set[str] = Field(default_factory=set)
    summary_name: str = ""

    @model_validator(mode="after")
    def set_workflow_file_stems(self) -> TFCITestInput:
        if not self.workflow_file_stems:
            self.workflow_file_stems = set(_TEST_STEMS)
        return self


def ci_tests(
    test_group_name: str = typer.Option("", "-g"),
    max_days_ago: int = typer.Option(1, "-d", "--days"),
    branch: str = typer.Option("master", "-b", "--branch"),
    workflow_file_stems: str = typer.Option("test-suite,terraform-compatibility-matrix", "-w", "--workflow"),
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
):
    names_set: set[str] = set()
    if names:
        names_set.update(names.split(","))
        logger.info(f"filtering tests by names: {names_set} (todo: support this)")
    if test_group_name:
        logger.warning(f"test_group_name is not supported yet: {test_group_name}")
    if summary_name:
        logger.warning(f"summary_name is not supported yet: {summary_name}")
    event = TFCITestInput(
        test_group_name=test_group_name,
        max_days_ago=max_days_ago,
        branch=branch,
        workflow_file_stems=set(workflow_file_stems.split(",")),
        names=names_set,
        summary_name=summary_name,
    )
    out = analyze_ci_tests(event)
    logger.info(f"found {len(out.log_paths)} log files with a total of {len(out.found_tests)} tests")
    summary_markdown = create_test_report(out.found_tests, out.found_errors)
    if summary_name:
        summary_path = event.settings.github_ci_summary_dir / str_utils.ensure_suffix(summary_name, ".md")
        summary_path.write_text(summary_markdown)
        logger.info(f"summary written to {summary_path}")
        if confirm(f"do you want to open the summary file? {summary_path}", default=False):
            run_command_receive_result(f'code "{summary_path}"', cwd=event.repo_path, logger=logger)


class TFCITestOutput(Entity):
    log_paths: list[Path] = Field(default_factory=list)
    found_tests: list[GoTestRun] = Field(default_factory=list)
    found_errors: list[GoTestError] = Field(default_factory=list)


def analyze_ci_tests(event: TFCITestInput) -> TFCITestOutput:
    repo_path = event.repo_path
    branch = event.branch
    token = run_command_receive_result("gh auth token", cwd=repo_path, logger=logger)
    os.environ[GH_TOKEN_ENV_NAME] = token
    settings = event.settings
    download_input = DownloadJobLogsInput(
        branch=branch,
        max_days_ago=event.max_days_ago,
        workflow_file_stems=event.workflow_file_stems,
    )
    log_paths = download_logs(download_input, settings)
    resources = read_tf_resources(settings, repo_path, branch)
    parse_job_output = parse_job_tf_test_logs(
        ParseJobLogsInput(
            settings=settings,
            log_paths=log_paths,
            resources=resources,
        )
    )
    found_tests = store_tf_test_runs(settings, parse_job_output.test_runs, overwrite=False)
    out = TFCITestOutput(log_paths=log_paths, found_tests=found_tests)
    admin_api_path = resolve_admin_api_path(sdk_branch="main")
    spec_paths = ApiSpecPaths(method_paths=parse_api_spec_paths(admin_api_path))
    out.found_errors = test_errors = parse_errors(parse_job_output, spec_paths, settings)
    classify_errors(test_errors, settings)
    return out


def classify_errors(errors: list[GoTestError], settings: AtlasInitSettings) -> None:
    known_errors: TFErrors = read_tf_errors(settings)
    needs_classification: list[GoTestError] = []
    for error in errors:
        if error.classifications:
            continue
        if auto_classification := GoTestErrorClass.auto_classification(error.run.output_lines_str):
            logger.info(f"auto classification for {error.run.name}: {auto_classification}")
            error.set_human_and_bot_classification(auto_classification)
            store_or_update_tf_errors(settings, [error])
            continue
        if existing_classifications := known_errors.look_for_existing_classifications(error):
            error.set_human_and_bot_classification(existing_classifications[-1])
            store_or_update_tf_errors(settings, [error])
        else:
            needs_classification.append(error)
    if add_bot_classification_changes(needs_classification, settings):
        store_or_update_tf_errors(settings, needs_classification)
    logger.info(f"found {len(needs_classification)} errors that need manual classification")
    manual_classification(settings, needs_classification)


def manual_classification(settings: AtlasInitSettings, needs_classification: list[GoTestError]):
    remaining_work = deque(needs_classification)
    while remaining_work:
        logger.info(f"remaining work: {len(remaining_work)}")
        error = remaining_work.popleft()
        if new_class := ask_user_to_classify_error(error):
            error.set_human_and_bot_classification(new_class)
            updated_errors = [error]
            if similar_matches := [similar_error for similar_error in remaining_work if similar_error.match(error)]:
                updated_errors.extend(similar_matches)
                logger.info(f"found {len(similar_matches)} similar matches for {error.run.name}, using {new_class}")
                for similar_error in similar_matches:
                    similar_error.set_human_and_bot_classification(new_class)
                    remaining_work.remove(similar_error)
            store_or_update_tf_errors(settings, [error])
        elif confirm("do you want to stop classifying errors?", default=True):
            logger.info("stopping classification")
            return


def add_bot_classification_changes(needs_classification_errors: list[GoTestError], settings: AtlasInitSettings) -> bool:
    """Todo: Use LLM"""
    example_errors = read_tf_errors(settings).classified_errors()
    if not example_errors:
        logger.warning("no example of classified errors found, the bot cannot classify errors without examples")
        return False
    return False


def parse_errors(
    parse_job_output: ParseJobLogsOutput,
    spec_paths: ApiSpecPaths | None,
    settings: AtlasInitSettings,
) -> list[GoTestError]:
    test_errors: list[GoTestError] = []
    for test in parse_job_output.tests_with_status(GoTestStatus.FAIL):
        if existing := read_tf_error_by_run(settings, test):
            test_errors.append(existing)
            continue
        test_error_input = ParseTestErrorInput(test=test, api_spec_paths=spec_paths)
        test_errors.append(parse_test_error(test_error_input))
    return test_errors


class DownloadJobLogsInput(Event):
    branch: str = "master"
    workflow_file_stems: set[str] = Field(default_factory=lambda: set(_TEST_STEMS))
    max_days_ago: int = 1


def download_logs(event: DownloadJobLogsInput, settings: AtlasInitSettings) -> list[Path]:
    end_test_date = utc_now()
    start_test_date = end_test_date - timedelta(days=event.max_days_ago)
    log_paths = []
    while start_test_date <= end_test_date:
        event_out = download_gh_job_logs(
            settings,
            DownloadJobRunsInput(branch=event.branch, run_date=start_test_date.date()),
        )
        log_paths.extend(event_out.log_paths)
        if errors := event_out.log_errors():
            logger.warning(errors)
        start_test_date += timedelta(days=1)
    return log_paths


_TEST_STEMS = {
    "test-suite",
    "terraform-compatibility-matrix",
    "acceptance-tests",
}


class DownloadJobRunsInput(Event):
    branch: str = "master"
    run_date: date
    workflow_file_stems: set[str] = Field(default_factory=lambda: set(_TEST_STEMS))
    worker_count: int = 10
    max_wait_seconds: int = 300


class DownloadJobRunsOutput(Entity):
    job_download_timeouts: int = 0
    job_download_empty: int = 0
    job_download_errors: int = 0
    log_paths: list[Path] = Field(default_factory=list)

    def log_errors(self) -> str:
        if not (self.job_download_timeouts or self.job_download_empty or self.job_download_errors):
            return ""
        return f"job_download_timeouts: {self.job_download_timeouts}, job_download_empty: {self.job_download_empty}, job_download_errors: {self.job_download_errors}"


def created_on_day(create: date) -> str:
    date_fmt = year_month_day(create)
    return f"{date_fmt}T00:00:00Z..{date_fmt}T23:59:59Z"


def year_month_day(create: date) -> str:
    return create.strftime("%Y-%m-%d")


def download_gh_job_logs(settings: AtlasInitSettings, event: DownloadJobRunsInput) -> DownloadJobRunsOutput:
    repository = tf_repo()
    branch = event.branch
    futures: list[Future[Path | None]] = []
    run_date = event.run_date
    out = DownloadJobRunsOutput()
    with ThreadPoolExecutor(max_workers=event.worker_count) as pool:
        for workflow in repository.get_workflow_runs(
            created=created_on_day(run_date),
            branch=branch,  # type: ignore
        ):
            workflow_stem = Path(workflow.path).stem
            if workflow_stem not in event.workflow_file_stems:
                continue
            workflow_dir = (
                settings.github_ci_run_logs / branch / year_month_day(run_date) / f"{workflow.id}_{workflow_stem}"
            )
            logger.info(f"workflow dir for {workflow_stem} @ {workflow.created_at.isoformat()}: {workflow_dir}")
            if workflow_dir.exists():
                paths = list(workflow_dir.rglob("*.log"))
                logger.info(f"found {len(paths)} logs in existing workflow dir: {workflow_dir}")
                out.log_paths.extend(paths)
                continue
            futures.extend(
                pool.submit(download_job_safely, workflow_dir, job)
                for job in workflow.jobs("all")
                if is_test_job(job.name)
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
    resources: TFResources


class ParseJobLogsOutput(Event):
    test_runs: list[GoTestRun] = Field(default_factory=list)

    def tests_with_status(self, status: GoTestStatus) -> list[GoTestRun]:
        return [test for test in self.test_runs if test.status == status]


def parse_job_tf_test_logs(
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
            test.resources = event.resources.find_test_resources(test)
        out.test_runs.extend(result)
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


class ParseTestErrorInput(Event):
    test: GoTestRun
    api_spec_paths: ApiSpecPaths | None = None


def parse_test_error(event: ParseTestErrorInput) -> GoTestError:
    run = event.test
    assert run.is_failure, f"test is not failed: {run.name}"
    details = parse_error_details(run)
    info = DetailsInfo(run=run, paths=event.api_spec_paths)
    details.add_info_fields(info)
    return GoTestError(details=details, run=run)


def ask_user_to_classify_error(error: GoTestError) -> GoTestErrorClass | None:
    test = error.run
    details = error.details
    return select_list(
        f"choose classification for {test.name_with_package} in {test.env} {details}\n{test.output_lines_str}\n",
        choices=list(GoTestErrorClass),
        default=error.bot_error_class,
    )
