import io
import logging
import os
import zipfile
from datetime import datetime
from functools import lru_cache
from pathlib import Path

import requests
from github import Auth, Github
from github.Repository import Repository
from zero_3rdparty import datetime_utils

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


def print_log_failures(since: datetime, max_downloads: int = MAX_DOWNLOADS):
    repository = get_repo(GH_OWNER_TERRAFORM_PROVIDER_MONGODBATLAS)
    auth = get_auth()
    headers = {
        "Authorization": f"{auth.token_type} {auth.token}",
        "Use-Agent": "PyGithub/Python",
    }
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
        dt = workflow.created_at
        dt_str = datetime_utils.get_date_as_rfc3339_without_time(dt)

        logs_url = workflow.logs_url
        logger.info(f"got workflow (#{found_workflows}): {workflow}")
        logger.info(f"created at: {dt}")
        logger.info(f"logs_url for: {workflow.name} {logs_url}")
        download_file(logs_url, headers, dt_str, str(workflow.id), workflow_name)
        if found_workflows > max_downloads:
            logger.warning(f"found {max_downloads}, exiting")
            return


def logs_dir() -> Path:
    return Path(os.environ[GITHUB_CI_RUN_LOGS_ENV_NAME])


def download_file(url: str, headers: dict, date_str: str, run_id: str, stem_name: str):
    rel_dir_path = f"{date_str}/{run_id}_{stem_name}"
    local_dir = logs_dir() / rel_dir_path
    if local_dir.exists():
        logger.info(f"skipping logs, already exists at {rel_dir_path}")
        return
    local_dir.mkdir(parents=True)
    logger.info(f"will write to {local_dir.absolute()}")
    with requests.get(url, stream=True, headers=headers, timeout=60) as r:
        if r.status_code == 404:  # noqa: PLR2004
            logger.warning(f"failed to download logs from {url} got 404")
            return
        r.raise_for_status()
        log_zip = io.BytesIO()
        for chunk in r.iter_content(chunk_size=8192):
            if chunk:
                log_zip.write(chunk)
        z = zipfile.ZipFile(log_zip)
        z.extractall(local_dir)
    return local_dir
