from pathlib import Path

from git import Repo

from atlas_init.config import ChangeGroup
from atlas_init.env_vars import REPO_PATH


def owner_project_name(repo_path: Path) -> str:
    raise NotImplementedError

def find_active_change_groups(repo_path: Path, repo_alias: str, groups: list[ChangeGroup]):
    repo = Repo(repo_path)
    for file in repo.head.commit.stats.files:
        print(f"changed: {file}")


if __name__ == "__main__":
    find_active_change_groups(REPO_PATH, "r1", [])