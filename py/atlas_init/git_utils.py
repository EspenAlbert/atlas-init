from pathlib import Path

from git import Repo


def owner_project_name(repo_path: Path) -> str:
    repo = Repo(repo_path)
    remote = repo.remotes[0]
    repo_url = list(remote.urls)[0]
    repo_url = repo_url.removesuffix(".git")
    *_, owner, project_name = repo_url.split("/")
    if ":" in owner:
        owner = owner.rsplit(":")[1]
    return f"{owner}/{project_name}"
