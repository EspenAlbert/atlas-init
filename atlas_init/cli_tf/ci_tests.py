from __future__ import annotations

import asyncio
import logging
import os
import re
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import date, datetime, timedelta
from pathlib import Path

import typer
from ask_shell import confirm, new_task, print_to_live, run_and_wait, select_list
from model_lib import Entity, Event, copy_and_validate
from pydantic import Field, ValidationError, field_validator, model_validator
from pydantic_core import Url
from rich.markdown import Markdown
from zero_3rdparty import file_utils
from zero_3rdparty.datetime_utils import utc_now
from zero_3rdparty.str_utils import ensure_suffix

from atlas_init.cli_helper.run import add_to_clipboard
from atlas_init.cli_tf.github_logs import (
    GH_TOKEN_ENV_NAME,
    download_job_safely,
    is_test_job,
    tf_repo,
)
from atlas_init.cli_tf.go_test_run import GoTestRun, GoTestStatus, parse_tests
from atlas_init.cli_tf.go_test_summary import (
    DailyReportIn,
    DailyReportOut,
    ErrorRowColumns,
    MonthlyReportIn,
    RunHistoryFilter,
    TFCITestOutput,
    TestRow,
    create_daily_report,
    create_monthly_report,
)
from atlas_init.cli_tf.go_test_tf_error import (
    DetailsInfo,
    ErrorClassAuthor,
    GoTestError,
    GoTestErrorClass,
    GoTestErrorClassification,
    parse_error_details,
)
from atlas_init.cli_tf.mock_tf_log import resolve_admin_api_path
from atlas_init.crud.mongo_dao import (
    TFResources,
    init_mongo_dao,
    read_tf_resources,
)
from atlas_init.html_out.md_export import MonthlyReportPaths, export_ci_tests_markdown_to_html
from atlas_init.repos.go_sdk import ApiSpecPaths, parse_api_spec_paths
from atlas_init.repos.path import Repo, current_repo_path
from atlas_init.settings.env_vars import AtlasInitSettings, init_settings

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

    @field_validator("report_date", mode="before")
    def support_today(cls, value: str | datetime) -> datetime | str:
        return utc_now() if isinstance(value, str) and value == "today" else value

    @model_validator(mode="after")
    def set_workflow_file_stems(self) -> TFCITestInput:
        if not self.workflow_file_stems:
            self.workflow_file_stems = set(_TEST_STEMS)
        return self


def ci_tests(
    test_group_name: str = typer.Option("", "-g"),
    max_days_ago: int = typer.Option(
        1, "-d", "--days", help="number of days to look back, Github only store logs for 30 days."
    ),
    branch: str = typer.Option("master", "-b", "--branch"),
    workflow_file_stems: str = typer.Option("test-suite,terraform-compatibility-matrix", "-w", "--workflow"),
    names: str = typer.Option(
        "",
        "-n",
        "--test-names",
        help="comma separated list of test names to filter, e.g., TestAccCloudProviderAccessAuthorizationAzure_basic,TestAccBackupSnapshotExportBucket_basicAzure",
    ),
    summary_name: str = typer.Option(
        ...,
        "-s",
        "--summary",
        help="the name of the summary directory to store detailed test results",
        default_factory=lambda: utc_now().strftime("%Y-%m-%d"),
    ),
    summary_env_name: str = typer.Option("", "--env", help="filter summary based on tests/errors only in dev/qa"),
    skip_log_download: bool = typer.Option(False, "-sld", "--skip-log-download", help="skip downloading logs"),
    skip_error_parsing: bool = typer.Option(
        False, "-sep", "--skip-error-parsing", help="skip parsing errors, usually together with --skip-log-download"
    ),
    skip_daily: bool = typer.Option(False, "-sd", "--skip-daily", help="skip daily report"),
    skip_monthly: bool = typer.Option(False, "-sm", "--skip-monthly", help="skip monthly report"),
    ask_to_open: bool = typer.Option(False, "--open", "--ask-to-open", help="ask to open the reports"),
    copy_to_clipboard: bool = typer.Option(
        False,
        "--copy",
        help="copy the summary to clipboard",
    ),
    report_date: str = typer.Option(
        "today",
        "-rd",
        "--report-day",
        help="the day to generate the report for, defaults to today, format=YYYY-MM-DD",
    ),
):
    names_set: set[str] = set()
    if names:
        names_set.update(names.split(","))
        logger.info(f"filtering tests by names: {names_set} (todo: support this)")
    if test_group_name:
        logger.warning(f"test_group_name is not supported yet: {test_group_name}")
    event = TFCITestInput(
        test_group_name=test_group_name,
        max_days_ago=max_days_ago,
        report_date=report_date,  # type: ignore
        branch=branch,
        workflow_file_stems=set(workflow_file_stems.split(",")),
        names=names_set,
        summary_name=summary_name,
        skip_log_download=skip_log_download,
        skip_error_parsing=skip_error_parsing,
    )
    history_filter = RunHistoryFilter(
        run_history_start=event.report_date - timedelta(days=event.max_days_ago),
        run_history_end=event.report_date,
        env_filter=[summary_env_name] if summary_env_name else [],
    )
    settings = event.settings
    report_paths = MonthlyReportPaths.from_settings(settings, summary_name)
    if skip_daily:
        logger.info("skipping daily report")
    else:
        run_daily_report(event, settings, history_filter, copy_to_clipboard, report_paths)
    if summary_name.lower() != "none":
        monthly_input = MonthlyReportIn(
            name=summary_name,
            branch=event.branch,
            history_filter=history_filter,
            report_paths=report_paths,
        )
        if skip_monthly:
            logger.info("skipping monthly report")
        else:
            generate_monthly_summary(settings, monthly_input, ask_to_open)
    export_ci_tests_markdown_to_html(settings, report_paths)


def run_daily_report(
    event: TFCITestInput,
    settings: AtlasInitSettings,
    history_filter: RunHistoryFilter,
    copy_to_clipboard: bool,
    report_paths: MonthlyReportPaths,
) -> DailyReportOut:
    out = asyncio.run(ci_tests_pipeline(event))
    manual_classification(out.classified_errors, settings)
    summary_name = event.summary_name

    def add_md_link(row: TestRow, row_dict: dict[str, str]) -> dict[str, str]:
        if not summary_name:
            return row_dict
        old_details = row_dict[ErrorRowColumns.DETAILS_SUMMARY]
        old_details = old_details or "Test History"
        row_dict[ErrorRowColumns.DETAILS_SUMMARY] = (
            f"[{old_details}]({settings.github_ci_summary_details_rel_path(summary_name, row.full_name)})"
        )
        return row_dict

    daily_in = DailyReportIn(
        report_date=event.report_date,
        history_filter=history_filter,
        row_modifier=add_md_link,
    )
    daily_out = create_daily_report(out, settings, daily_in)
    print_to_live(Markdown(daily_out.summary_md))
    if copy_to_clipboard:
        add_to_clipboard(daily_out.summary_md, logger=logger)
    file_utils.ensure_parents_write_text(report_paths.daily_path, daily_out.summary_md)
    return daily_out


def generate_monthly_summary(
    settings: AtlasInitSettings, monthly_input: MonthlyReportIn, ask_to_open: bool = False
) -> None:
    monthly_out = create_monthly_report(
        settings,
        monthly_input,
    )
    paths = monthly_input.report_paths
    summary_path = paths.summary_path
    file_utils.ensure_parents_write_text(summary_path, monthly_out.summary_md)
    logger.info(f"summary written to {summary_path}")
    details_dir = paths.details_dir
    file_utils.clean_dir(details_dir, recreate=True)
    logger.info(f"Writing details to {details_dir}")
    for name, details_md in monthly_out.test_details_md.items():
        details_path = details_dir / ensure_suffix(name, ".md")
        file_utils.ensure_parents_write_text(details_path, details_md)
    monthly_error_only_out = create_monthly_report(
        settings,
        event=copy_and_validate(
            monthly_input,
            skip_rows=[MonthlyReportIn.skip_if_no_failures],
            existing_details_md=monthly_out.test_details_md,
        ),
    )
    error_only_path = paths.error_only_path
    file_utils.ensure_parents_write_text(error_only_path, monthly_error_only_out.summary_md)
    logger.info(f"error-only summary written to {error_only_path}")
    if ask_to_open and confirm(f"do you want to open the summary file? {summary_path}", default=False):
        run_and_wait(f'code "{summary_path}"')
    if ask_to_open and confirm(f"do you want to open the error-only summary file? {error_only_path}", default=False):
        run_and_wait(f'code "{error_only_path}"')
    return None


async def ci_tests_pipeline(event: TFCITestInput) -> TFCITestOutput:
    repo_path = event.repo_path
    branch = event.branch
    settings = event.settings
    download_input = DownloadJobLogsInput(
        branch=branch,
        max_days_ago=event.max_days_ago,
        end_date=event.report_date,
        workflow_file_stems=event.workflow_file_stems,
        repo_path=repo_path,
    )
    dao = await init_mongo_dao(settings)
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
        await dao.store_tf_test_runs(parse_job_output.test_runs)
    report_date = event.report_date
    with new_task(f"reading test runs from storage for {report_date.date().isoformat()}"):
        report_tests = await dao.read_tf_tests_for_day(event.branch, report_date)
    with new_task("parsing test errors"):
        report_errors = parse_test_errors(report_tests)
    with new_task("classifying errors"):
        error_run_ids = [error.run_id for error in report_errors]
        existing_classifications = await dao.read_error_classifications(error_run_ids)
        classified_errors = classify_errors(existing_classifications, report_errors)
    return TFCITestOutput(
        log_paths=log_paths, found_tests=report_tests, classified_errors=classified_errors, found_errors=report_errors
    )


def parse_test_errors(found_tests: list[GoTestRun]) -> list[GoTestError]:
    admin_api_path = resolve_admin_api_path(sdk_branch="main")
    spec_paths = ApiSpecPaths(method_paths=parse_api_spec_paths(admin_api_path))
    error_tests = [test for test in found_tests if test.is_failure]
    test_errors: list[GoTestError] = []
    for test in error_tests:
        test_error_input = ParseTestErrorInput(test=test, api_spec_paths=spec_paths)
        test_errors.append(parse_test_error(test_error_input))
    return test_errors


def classify_errors(
    existing: dict[str, GoTestErrorClassification], errors: list[GoTestError]
) -> list[GoTestErrorClassification]:
    needs_classification: list[GoTestError] = []
    classified_errors: list[GoTestErrorClassification] = []
    for error in errors:
        if prev_classification := existing.get(error.run_id):
            logger.info(f"found existing classification{error.run_name}: {prev_classification}")
            classified_errors.append(prev_classification)
            continue
        if auto_class := GoTestErrorClass.auto_classification(error.run.output_lines_str):
            logger.info(f"auto class for {error.run_name}: {auto_class}")
            classified_errors.append(
                GoTestErrorClassification(
                    error_class=auto_class,
                    confidence=1.0,
                    details=error.details,
                    test_output=error.run.output_lines_str,
                    run_id=error.run_id,
                    author=ErrorClassAuthor.AUTO,
                    test_name=error.run_name,
                )
            )
        else:
            needs_classification.append(error)
    return classified_errors + add_llm_classifications(needs_classification)


def manual_classification(
    classifications: list[GoTestErrorClassification], settings: AtlasInitSettings, confidence_threshold: float = 1.0
):
    needs_classification = [cls for cls in classifications if cls.needs_classification(confidence_threshold)]
    with new_task("Manual Classification", total=len(needs_classification) + 1, log_updates=True) as task:
        asyncio.run(classify(needs_classification, settings, task))


async def classify(
    needs_classification: list[GoTestErrorClassification], settings: AtlasInitSettings, task: new_task
) -> None:
    dao = await init_mongo_dao(settings)

    async def add_classification(
        cls: GoTestErrorClassification, new_class: GoTestErrorClass, new_author: ErrorClassAuthor, confidence: float
    ):
        cls.error_class = new_class
        cls.author = new_author
        cls.confidence = confidence
        is_new = await dao.add_classification(cls)
        if not is_new:
            logger.debug("replaced existing class")

    for cls in needs_classification:
        task.update(advance=1)
        similars = await dao.read_similar_error_classifications(cls.details, author_filter=ErrorClassAuthor.HUMAN)
        if (existing := similars.get(cls.run_id)) and not existing.needs_classification():
            logger.debug(f"found existing classification: {existing}")
            continue
        if similars and len({similar.error_class for similar in similars.values()}) == 1:
            _, similar = similars.popitem()
            if not similar.needs_classification(0.0):
                logger.info(f"using similar classification: {similar}")
                await add_classification(cls, similar.error_class, ErrorClassAuthor.SIMILAR, 1.0)
                continue
        test = await dao.read_tf_test_run(cls.run_id)
        if new_class := ask_user_to_classify_error(cls, test):
            await add_classification(cls, new_class, ErrorClassAuthor.HUMAN, 1.0)
        elif confirm("do you want to stop classifying errors?", default=True):
            logger.info("stopping classification")
            return


def add_llm_classifications(needs_classification_errors: list[GoTestError]) -> list[GoTestErrorClassification]:
    """Todo: Use LLM and support reading existing classifications, for example matching on the details"""
    return [
        GoTestErrorClassification(
            ts=utc_now(),
            error_class=GoTestErrorClass.UNKNOWN,
            confidence=0.0,
            details=error.details,
            test_output=error.run.output_lines_str,
            run_id=error.run_id,
            author=ErrorClassAuthor.LLM,
            test_name=error.run_name,
        )
        for error in needs_classification_errors
    ]


class DownloadJobLogsInput(Entity):
    branch: str = "master"
    workflow_file_stems: set[str] = Field(default_factory=lambda: set(_TEST_STEMS))
    max_days_ago: int = 1
    end_date: datetime = Field(default_factory=utc_now)
    repo_path: Path

    @property
    def start_date(self) -> datetime:
        return self.end_date - timedelta(days=self.max_days_ago)

    @model_validator(mode="after")
    def check_max_days_ago(self) -> DownloadJobLogsInput:
        if self.max_days_ago > 90:
            logger.warning(f"max_days_ago for {type(self).__name__} must be less than or equal to 90, setting to 90")
            self.max_days_ago = 90
        return self


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
        try:
            result = parse_tests(log_text.splitlines())
        except ValidationError as e:
            logger.warning(f"failed to parse tests from {log_path}: {e}")
            continue
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


def ask_user_to_classify_error(cls: GoTestErrorClassification, test: GoTestRun) -> GoTestErrorClass | None:
    details = cls.details
    try:
        print_to_live(test.output_lines_str)
        print_to_live(f"error details: {details}")
        return select_list(
            f"choose classification for test='{test.name_with_package}' in {test.env}",
            choices=list(GoTestErrorClass),
            default=cls.error_class,
        )  # type: ignore
    except KeyboardInterrupt:
        return None
