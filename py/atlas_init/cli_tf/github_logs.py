import logging
import os
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import requests
from github import Auth, Github
from github.Repository import Repository
from github.WorkflowJob import WorkflowJob
from github.WorkflowRun import WorkflowRun
from github.WorkflowStep import WorkflowStep
from zero_3rdparty import datetime_utils, file_utils

from atlas_init.cli_tf.go_test_run import parse
from atlas_init.repos.path import (
    GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS,
)

logger = logging.getLogger(__name__)

GH_TOKEN_ENV_NAME = "GH_TOKEN"  # noqa: S105
GITHUB_CI_RUN_LOGS_ENV_NAME = "GITHUB_CI_RUN_LOGS"
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


_USED_FILESTEMS = {
    "test-suite",
    "terraform-compatibility-matrix",
}


def stem_name(workflow_path: str) -> str:
    return Path(workflow_path).stem


def tf_repo() -> Repository:
    return get_repo(GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS)


def print_log_failures(since: datetime, max_downloads: int = MAX_DOWNLOADS):
    repository = tf_repo()
    found_workflows = 0
    for workflow in repository.get_workflow_runs(
        created=f">{since.strftime('%Y-%m-%d')}",
        branch="master",
        exclude_pull_requests=True,  # type: ignore
    ):
        workflow_name = stem_name(workflow.path)
        if workflow_name not in _USED_FILESTEMS:
            continue
        found_workflows += 1
        logger.info(f"got workflow (#{found_workflows}): {workflow}")
        download_workflow_logs(workflow)
        if found_workflows > max_downloads:
            logger.warning(f"found {max_downloads}, exiting")
            return


def download_workflow_logs(workflow: WorkflowRun, *, force: bool = False):
    workflow_dir = workflow_logs_dir(workflow)
    if workflow_dir.exists() and not force:
        logger.info(f"dir {workflow_dir} exists for {workflow.html_url}")
        return
    paginated_jobs = workflow.jobs("all")
    for job in paginated_jobs:
        if not is_test_job(job.name):
            continue
        path = logs_file(workflow_dir, job)
        logger.info(
            f"found test job: {job.name}, attempt {job.run_attempt}, {job.created_at}, url: {job.html_url}\n\t\t downloading to {path}"
        )
        try:
            logs_response = requests.get(job.logs_url(), timeout=60)
            logs_response.raise_for_status()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"failed to download logs for {job.html_url}, e={e!r}")
            continue
        file_utils.ensure_parents_write_text(path, logs_response.text)
        step, logs_lines = select_step_and_log_content(job, path)
        for go_test in parse(logs_lines, job, step):
            if go_test.is_failure:
                logger.warning(f"found failing go test: {go_test.name} @ {go_test.url}")
        # TODO: also insert to a database


def logs_dir() -> Path:
    return Path(os.environ[GITHUB_CI_RUN_LOGS_ENV_NAME])


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
        if "test" in step.name.lower():
            return i
    last_step = len(steps)
    logger.warning(f"using {last_step} as final step, unable to find 'test' in {steps}")
    return last_step
