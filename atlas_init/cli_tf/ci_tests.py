from __future__ import annotations

import logging
import os
import re
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta
from pathlib import Path

import typer
from ask_shell import run_and_wait
from ask_shell.rich_progress import new_task
from ask_shell.rich_live import print_to_live_console
from model_lib import Entity, Event
from pydantic import Field, model_validator
from pydantic_core import Url
from rich.markdown import Markdown
from zero_3rdparty import file_utils, str_utils
from zero_3rdparty.datetime_utils import utc_now

from atlas_init.cli_helper.run import run_command_receive_result
from atlas_init.cli_tf.github_logs import (
    GH_TOKEN_ENV_NAME,
    download_job_safely,
    is_test_job,
    tf_repo,
)
from atlas_init.cli_tf.go_test_run import GoTestRun, GoTestStatus, parse_tests
from atlas_init.cli_tf.go_test_summary import TFCITestOutput, create_daily_report
from atlas_init.cli_tf.go_test_tf_error import (
    DetailsInfo,
    GoTestError,
    GoTestErrorClass,
    GoTestErrorClassification,
    GoTestErrorClassificationAuthor,
    parse_error_details,
)
from atlas_init.cli_tf.mock_tf_log import resolve_admin_api_path
from atlas_init.crud.tf_resource import (
    TFResources,
    read_tf_error_by_run,
    read_tf_errors,
    read_tf_errors_for_day,
    read_tf_resources,
    read_tf_tests_for_day,
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
    skip_log_download: bool = False
    skip_error_parsing: bool = False
    summary_name: str = ""
    report_date: datetime = Field(default_factory=utc_now)

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
    summary_env_name: str = typer.Option("", "--env", help="filter summary based on tests/errors only in dev/qa"),
    skip_log_download: bool = typer.Option(False, "-sld", "--skip-log-download", help="skip downloading logs"),
    skip_error_parsing: bool = typer.Option(
        False, "-sep", "--skip-error-parsing", help="skip parsing errors, usually together with --skip-log-download"
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
        skip_log_download=skip_log_download,
        skip_error_parsing=skip_error_parsing,
    )
    out = ci_tests_pipeline(event)
    logger.info("will later add support for adding manual classifications")
    daily = create_daily_report(out)
    print_to_live_console(Markdown(daily.summary_md))
    if summary_name:
        summary_path = event.settings.github_ci_summary_dir / str_utils.ensure_suffix(summary_name, ".md")
        file_utils.ensure_parents_write_text(summary_path, daily.summary_md)
        logger.info(f"summary written to {summary_path}")
        if report_details_md := daily.details_md:
            details_path = summary_path.with_name(f"{summary_path.stem}_details.md")
            file_utils.ensure_parents_write_text(details_path, report_details_md)
            logger.info(f"summary details written to {details_path}")
        if confirm(f"do you want to open the summary file? {summary_path}", default=False):
            run_command_receive_result(f'code "{summary_path}"', cwd=event.repo_path, logger=logger)


def ci_tests_pipeline(event: TFCITestInput) -> TFCITestOutput:
    repo_path = event.repo_path
    branch = event.branch
    settings = event.settings
    download_input = DownloadJobLogsInput(
        branch=branch,
        max_days_ago=event.max_days_ago,
        workflow_file_stems=event.workflow_file_stems,
        repo_path=repo_path,
    )
    if event.skip_log_download:
        logger.info("skipping log download, reading existing instead")
        log_paths = []
    else:
        log_paths = download_logs(download_input, settings)
        resources = read_tf_resources(settings, repo_path, branch)
        with new_task(f"parse job logs from {len(log_paths)} files"):
            parse_job_output = parse_job_tf_test_logs(
                ParseJobLogsInput(
                    settings=settings,
                    log_paths=log_paths,
                    resources=resources,
                    branch=branch,
                )
            )
        store_tf_test_runs(settings, parse_job_output.test_runs, overwrite=True)
    with new_task("reading test runs from storage"):
        found_tests = read_tf_tests_for_day(settings, event.branch, event.report_date)
    if event.skip_error_parsing:
        with new_task("skipping error parsing, reading existing errors"):
            test_errors = read_tf_errors_for_day(settings, event.branch, event.report_date)
    else:
        with new_task("parsing test errors"):
            test_errors = parse_test_errors(settings, found_tests)
    with new_task("classifying errors"):
        classified_errors = classify_errors(test_errors, settings)
    return TFCITestOutput(log_paths=log_paths, found_tests=found_tests, classified_errors=classified_errors)


def parse_test_errors(settings: AtlasInitSettings, found_tests: list[GoTestRun]) -> list[GoTestError]:
    admin_api_path = resolve_admin_api_path(sdk_branch="main")
    spec_paths = ApiSpecPaths(method_paths=parse_api_spec_paths(admin_api_path))
    error_tests = [test for test in found_tests if test.is_failure]
    return parse_errors(error_tests, spec_paths, settings)


def classify_errors(errors: list[GoTestError], settings: AtlasInitSettings) -> list[GoTestErrorClassification]:
    needs_classification: list[GoTestError] = []
    classified_errors: list[GoTestErrorClassification] = []
    for error in errors:
        if auto_class := GoTestErrorClass.auto_classification(error.run.output_lines_str):
            logger.info(f"auto class for {error.run.name}: {auto_class}")
            classified_errors.append(
                GoTestErrorClassification(
                    error_class=auto_class,
                    confidence=1.0,
                    details=error.details,
                    test_output=error.run.output_lines_str,
                    run_id=error.run_id,
                    author=GoTestErrorClassificationAuthor.AUTO,
                )
            )
        else:
            needs_classification.append(error)
    # todo: support reading existing classifications, for example matching on the details
    return classified_errors + add_llm_classifications(needs_classification, settings)


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


def add_llm_classifications(
    needs_classification_errors: list[GoTestError], settings: AtlasInitSettings
) -> list[GoTestErrorClassification]:
    """Todo: Use LLM"""
    example_errors = read_tf_errors(settings).classified_errors()
    if not example_errors:
        logger.warning("no example of classified errors found, the bot cannot classify errors without examples")
        return []
    return []


def parse_errors(
    error_tests: list[GoTestRun],
    spec_paths: ApiSpecPaths | None,
    settings: AtlasInitSettings,
) -> list[GoTestError]:
    test_errors: list[GoTestError] = []
    for test in error_tests:
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
    end_date: datetime = Field(default_factory=utc_now)
    repo_path: Path

    @property
    def start_date(self) -> datetime:
        return self.end_date - timedelta(days=self.max_days_ago)


def download_logs(event: DownloadJobLogsInput, settings: AtlasInitSettings) -> list[Path]:
    token = run_and_wait("gh auth token", cwd=event.repo_path).stdout
    assert token, "expected token, but got empty string"
    os.environ[GH_TOKEN_ENV_NAME] = token
    end_test_date = event.end_date
    start_test_date = event.start_date
    log_paths = []
    with new_task(
        f"downloading logs for {event.branch} from {start_test_date.date()} to {end_test_date.date()}",
        total=(end_test_date - start_test_date).days,
    ) as task:
        while start_test_date <= end_test_date:
            event_out = download_gh_job_logs(
                settings,
                DownloadJobRunsInput(branch=event.branch, run_date=start_test_date.date()),
            )
            log_paths.extend(event_out.log_paths)
            if errors := event_out.log_errors():
                logger.warning(errors)
            start_test_date += timedelta(days=1)
            task.update(advance=1)
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
    branch: str


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
            test.branch = event.branch
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
