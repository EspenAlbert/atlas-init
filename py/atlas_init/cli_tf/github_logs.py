import logging
import os
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor, wait
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from typing import NamedTuple

import requests
from github import Auth, Github
from github.Repository import Repository
from github.WorkflowJob import WorkflowJob
from github.WorkflowRun import WorkflowRun
from github.WorkflowStep import WorkflowStep
from zero_3rdparty import datetime_utils, file_utils

from atlas_init.cli_tf.go_test_run import GoTestRun, parse
from atlas_init.repos.path import (
    GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS,
)
from atlas_init.settings.path import (
    DEFAULT_GITHUB_CI_RUN_LOGS,
    DEFAULT_GITHUB_SUMMARY_DIR,
)

logger = logging.getLogger(__name__)

GH_TOKEN_ENV_NAME = "GH_TOKEN"  # noqa: S105
GITHUB_CI_RUN_LOGS_ENV_NAME = "GITHUB_CI_RUN_LOGS"
GITHUB_CI_SUMMARY_DIR_ENV_NAME = "GITHUB_CI_SUMMARY_DIR_ENV_NAME"
REQUIRED_GH_ENV_VARS = [GH_TOKEN_ENV_NAME, GITHUB_CI_RUN_LOGS_ENV_NAME]
MAX_DOWNLOADS = 5


@lru_cache
def get_auth() -> Auth.Auth:
    token = os.environ[GH_TOKEN_ENV_NAME]
    return Auth.Token(token)


@lru_cache
def get_repo(repo_id: str) -> Repository:
    auth = get_auth()
    g = Github(auth=auth)
    logger.info(f"logged in as: {g.get_user().login}")
    return g.get_repo(repo_id)


_DEFAULT_FILESTEMS = {
    "test-suite",
    "terraform-compatibility-matrix",
    # "acceptance-tests",
}


def include_filestems(stems: set[str]) -> Callable[[WorkflowRun], bool]:
    def inner(run: WorkflowRun) -> bool:
        workflow_stem = stem_name(run.path)
        return workflow_stem in stems

    return inner


def stem_name(workflow_path: str) -> str:
    return Path(workflow_path).stem


def tf_repo() -> Repository:
    return get_repo(GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS)


class WorkflowJobId(NamedTuple):
    workflow_id: int
    job_id: int


def find_test_runs(
    since: datetime,
    include_workflow: Callable[[WorkflowRun], bool] | None = None,
    include_job: Callable[[WorkflowJob], bool] | None = None,
    branch: str = "master",
) -> dict[WorkflowJobId, list[GoTestRun]]:
    include_workflow = include_workflow or include_filestems(_DEFAULT_FILESTEMS)
    include_job = include_job or include_test_jobs()
    jobs_found = defaultdict(list)
    repository = tf_repo()
    for workflow in repository.get_workflow_runs(
        created=f">{since.strftime('%Y-%m-%d')}",
        branch=branch,
        exclude_pull_requests=True,  # type: ignore
    ):
        if not include_workflow(workflow):
            continue
        workflow_dir = workflow_logs_dir(workflow)
        paginated_jobs = workflow.jobs("all")
        worker_count = min(paginated_jobs.totalCount, 10) or 1
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures: dict[Future[list[GoTestRun]], WorkflowJob] = {}
            for job in paginated_jobs:
                if not include_job(job):
                    continue
                future = pool.submit(find_job_test_runs, workflow_dir, job)
                futures[future] = job
            done, not_done = wait(futures.keys(), timeout=300)
            for f in not_done:
                logger.warning(f"timeout to find go tests for job = {futures[f].html_url}")
        workflow_id = workflow.id
        for f in done:
            job = futures[f]
            try:
                go_test_runs: list[GoTestRun] = f.result()
            except Exception:
                job_log_path = logs_file(workflow_dir, job)
                logger.exception(
                    f"failed to find go tests for job: {job.html_url}, error 👆, local_path: {job_log_path}"
                )
                continue
            jobs_found[WorkflowJobId(workflow_id, job.id)].extend(go_test_runs)
    return jobs_found


def find_job_test_runs(workflow_dir: Path, job: WorkflowJob) -> list[GoTestRun]:
    jobs_log_path = download_job_safely(workflow_dir, job)
    return [] if jobs_log_path is None else parse_job_logs(job, jobs_log_path)


def parse_job_logs(job: WorkflowJob, logs_path: Path) -> list[GoTestRun]:
    step, logs_lines = select_step_and_log_content(job, logs_path)
    return list(parse(logs_lines, job, step))


def download_job_safely(workflow_dir: Path, job: WorkflowJob) -> Path | None:
    path = logs_file(workflow_dir, job)
    job_summary = f"found test job: {job.name}, attempt {job.run_attempt}, {job.created_at}, url: {job.html_url}"
    if path.exists():
        logger.info(f"{job_summary} exist @ {path}")
        return path
    logger.info(f"{job_summary}\n\t\t downloading to {path}")
    try:
        logs_response = requests.get(job.logs_url(), timeout=60)
        logs_response.raise_for_status()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"failed to download logs for {job.html_url}, e={e!r}")
        return None
    file_utils.ensure_parents_write_text(path, logs_response.text)
    return path


def logs_dir() -> Path:
    logs_dir_str = os.environ.get(GITHUB_CI_RUN_LOGS_ENV_NAME)
    if not logs_dir_str:
        logger.warning(f"using {DEFAULT_GITHUB_CI_RUN_LOGS} to store github ci logs!")
        return DEFAULT_GITHUB_CI_RUN_LOGS
    return Path(logs_dir_str)


def summary_dir(summary_name: str) -> Path:
    summary_dir_str = os.environ.get(GITHUB_CI_SUMMARY_DIR_ENV_NAME)
    if not summary_dir_str:
        logger.warning(f"using {DEFAULT_GITHUB_SUMMARY_DIR / summary_name} to store summaries")
        return DEFAULT_GITHUB_SUMMARY_DIR / summary_name
    return Path(summary_dir_str) / summary_name


def workflow_logs_dir(workflow: WorkflowRun) -> Path:
    dt = workflow.created_at
    date_str = datetime_utils.get_date_as_rfc3339_without_time(dt)
    workflow_name = stem_name(workflow.path)
    return logs_dir() / f"{date_str}/{workflow.id}_{workflow_name}"


def logs_file(workflow_dir: Path, job: WorkflowJob) -> Path:
    if job.run_attempt != 1:
        workflow_dir = workflow_dir.with_name(f"{workflow_dir.name}_attempt{job.run_attempt}")
    filename = f"{job.id}_" + job.name.replace(" ", "").replace("/", "_").replace("__", "_") + ".txt"
    return workflow_dir / filename


def as_test_group(job_name: str) -> str:
    """tests-1.8.x-latest / tests-1.8.x-latest-dev / config"""
    return "" if "/" not in job_name else job_name.split("/")[-1].strip()


def include_test_jobs(test_group: str = "") -> Callable[[WorkflowJob], bool]:
    def inner(job: WorkflowJob) -> bool:
        job_name = job.name
        if test_group:
            return is_test_job(job_name) and as_test_group(job_name) == test_group
        return is_test_job(job.name)

    return inner


def is_test_job(job_name: str) -> bool:
    """
    >>> is_test_job("tests-1.8.x-latest / tests-1.8.x-latest-dev / config")
    True
    """
    if "-before" in job_name or "-after" in job_name:
        return False
    return "tests-" in job_name and not job_name.endswith(("get-provider-version", "change-detection"))


def select_step_and_log_content(job: WorkflowJob, logs_path: Path) -> tuple[int, list[str]]:
    full_text = logs_path.read_text()
    step = test_step(job.steps)
    last_step_start = current_step_start = 1
    # there is always an extra setup job step, so starting at 1
    current_step = 1
    lines = full_text.splitlines()
    for line_index, line in enumerate(lines, 0):
        if "##[group]Run " in line:
            current_step += 1
            last_step_start, current_step_start = current_step_start, line_index
            if current_step == step + 1:
                return step, lines[last_step_start:current_step_start]
    assert step == current_step, f"didn't find enough step in logs for {job.html_url}"
    return step, lines[current_step_start:]


def test_step(steps: list[WorkflowStep]) -> int:
    for i, step in enumerate(steps, 1):
        name_lower = step.name.lower()
        if "acceptance test" in name_lower and "mocked" not in name_lower:
            return i
    last_step = len(steps)
    logger.warning(f"using {last_step} as final step, unable to find 'test' in {steps}")
    return last_step
