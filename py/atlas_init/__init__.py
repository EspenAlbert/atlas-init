from pathlib import Path

VERSION = "0.1.1"
PY_DIRECTORY = Path(__file__).parent.parent


def running_in_repo() -> bool:
    if PY_DIRECTORY.name != "py":
        return False
    git_directory = PY_DIRECTORY.parent / ".git"
    fetch_head = git_directory / "FETCH_HEAD"
    return git_directory.exists() and fetch_head.exists() and "atlas-init" in fetch_head.read_text()
