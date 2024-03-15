import os
from pathlib import Path

from git import Repo

from atlas_init.config import TestSuit
from atlas_init.env_vars import REPO_PATH


def owner_project_name(repo_path: Path) -> str:
    repo = Repo(repo_path)
    remote = repo.remotes[0]
    repo_url = list(remote.urls)[0]
    repo_url = repo_url.removesuffix(".git")
    *_, owner, project_name = repo_url.split("/")
    if ":" in owner:
        owner = owner.rsplit(":")[1]
    return f"{owner}/{project_name}"


def find_active_test_suites(repo_path: Path, repo_alias: str, groups: list[TestSuit]):
    repo = Repo(repo_path)
    for file in repo.head.commit.stats.files:
        print(f"changed: {file}")

    # https://gitpython.readthedocs.io/en/stable/quickstart.html
    # if repo.is_dirty:
    #     repo.untracked_files
    #     index = repo.working_dir
    #     diff = index.diff(None)
    #     for (file, _) in diff.index.entries:
    #         print(f"dirty: {file}")
    # else:


if __name__ == "__main__":
    find_active_test_suites(REPO_PATH, "r1", [])
    print(owner_project_name(os.environ["REPO_PATH"]))
