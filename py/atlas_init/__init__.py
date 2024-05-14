VERSION = "0.0.1"
RUNNING_IN_REPO = True


def running_in_repo() -> bool:
    """RUNNING_IN_REPO is updated during packaging"""
    return RUNNING_IN_REPO
