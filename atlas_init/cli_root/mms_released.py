import logging
from pathlib import Path

import requests
import typer
from atlas_init.typer_app import app_command
from git import Repo

logger = logging.getLogger(__name__)


@app_command()
def mms_released(
    mms_repo: Path = typer.Option(..., "-r", "--mms-repo", help="the path to the mms repo"),
    commit_shas: list[str] = typer.Option(
        ..., "-c", "--commit-shas", help="the commit shas to check for release, can be set multiple times"
    ),
    sha_url: str = typer.Option(
        "https://cloud.mongodb.com/api/private/unauth/version",
        "-u",
        "--url",
        help="the url to get the current sha from",
    ),
):
    assert mms_repo.exists(), f"mms repo not found @ {mms_repo}"
    git_repo = Repo(mms_repo)
    git_repo.git.fetch("origin")
    for sha in commit_shas:
        assert git_repo.commit(sha), f"commit {sha} not found in {mms_repo}"
    current_sha_response = requests.get(sha_url, timeout=10)
    current_sha_response.raise_for_status()
    current_sha = current_sha_response.text.strip()
    assert current_sha, f"unable to get current sha from {current_sha_response.url}"
    logger.info(f"current sha of prod: {current_sha}")
    assert git_repo.commit(current_sha)
    remaining_shas = set(commit_shas)
    for commit in git_repo.iter_commits(rev=current_sha):
        commit_sha = commit.hexsha
        if commit_sha in commit_shas:
            commit_message = commit.message.rstrip("\n")  # type: ignore
            logger.info(f"found commit {commit_sha} with message {commit_message}")
            remaining_shas.remove(commit_sha)
        if not remaining_shas:
            logger.info("all commits found ✅")
            return
    logger.info(f"remaining shas: {','.join(sorted(remaining_shas))} ❌")
