from pathlib import Path

VERSION = "0.4.3"


def running_in_repo() -> bool:
    maybe_git_directory = Path(__file__).parent.parent / ".git"
    git_config = maybe_git_directory / "config"
    return git_config.exists() and "atlas-init" in git_config.read_text()
