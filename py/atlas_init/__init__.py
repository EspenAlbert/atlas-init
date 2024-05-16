from pathlib import Path

VERSION = "0.1.1"


def running_in_repo() -> bool:
    py_directory = Path(__file__).parent.parent
    if py_directory.name != "py":
        return False
    git_directory = py_directory.parent / ".git"
    fetch_head = git_directory / "FETCH_HEAD"
    return git_directory.exists() and fetch_head.exists() and "atlas-init" in fetch_head.read_text()
