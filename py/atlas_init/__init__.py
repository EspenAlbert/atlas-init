from pathlib import Path

VERSION = "0.3.6"


def running_in_repo() -> bool:
    py_directory = Path(__file__).parent.parent
    if py_directory.name != "py":
        return False
    git_directory = py_directory.parent / ".git"
    git_config = git_directory / "config"
    return git_directory.exists() and git_config.exists() and "atlas-init" in git_config.read_text()
