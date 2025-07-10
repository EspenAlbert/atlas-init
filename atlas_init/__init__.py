from pathlib import Path

VERSION = "0.7.0"


def running_in_repo() -> bool:
    git_config = Path(__file__).parent.parent / ".git/config"
    return git_config.exists() and "atlas-init" in git_config.read_text()
