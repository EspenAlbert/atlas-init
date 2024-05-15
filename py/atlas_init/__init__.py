from pathlib import Path

VERSION = "0.0.2"


def running_in_repo() -> bool:
    git_directory = Path(__file__).parent.parent.parent / ".git"
    fetch_head = git_directory / "FETCH_HEAD"
    return git_directory.exists() and fetch_head.exists() and "atlas-init" in fetch_head.read_text()
