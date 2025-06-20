import logging
import os
from collections.abc import Callable
from functools import lru_cache
from pathlib import Path

import requests
from github import Auth, Github
from github.Repository import Repository
from github.WorkflowJob import WorkflowJob
from github.WorkflowRun import WorkflowRun
from github.WorkflowStep import WorkflowStep
from zero_3rdparty import datetime_utils, file_utils

from atlas_init.repos.path import (
    GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS,
)
from atlas_init.settings.env_vars import init_settings

logger = logging.getLogger(__name__)

GH_TOKEN_ENV_NAME = "GH_TOKEN"  # noqa: S105 #nosec
REQUIRED_GH_ENV_VARS = [GH_TOKEN_ENV_NAME]
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


def tf_repo() -> Repository:
    return get_repo(GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS)


def download_job_safely(workflow_dir: Path, job: WorkflowJob) -> Path | None:
    if job.conclusion in {"skipped", "cancelled", None}:
        logger.debug(f"not downloading job: {job.html_url}, conclusion: {job.conclusion}")
        return None
    path = logs_file(workflow_dir, job)
    job_summary = f"found test job: {job.name}, attempt {job.run_attempt}, {job.created_at}, url: {job.html_url}"
    if path.exists():
        logger.debug(f"{job_summary} exist @ {path}")
        return path
    logger.debug(f"{job_summary}\n\t\t downloading to {path}")
    try:
        logs_response = requests.get(job.logs_url(), timeout=60)
        logs_response.raise_for_status()
    except Exception as e:  # noqa: BLE001
        logger.warning(f"failed to download logs for {job.html_url}, e={e!r}")
        return None
    file_utils.ensure_parents_write_text(path, logs_response.text)
    return path


def logs_dir() -> Path:
    return init_settings().github_ci_run_logs


def summary_dir(summary_name: str) -> Path:
    return init_settings().github_ci_summary_dir / summary_name


def workflow_logs_dir(workflow: WorkflowRun) -> Path:
    dt = workflow.created_at
    date_str = datetime_utils.get_date_as_rfc3339_without_time(dt)
    workflow_name = Path(workflow.path).stem
    return logs_dir() / f"{date_str}/{workflow.id}_{workflow_name}"


def logs_file(workflow_dir: Path, job: WorkflowJob) -> Path:
    if job.run_attempt != 1:
        workflow_dir = workflow_dir.with_name(f"{workflow_dir.name}_attempt{job.run_attempt}")
    filename = f"{job.id}_" + job.name.replace(" ", "").replace("/", "_").replace("__", "_") + ".log"
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
