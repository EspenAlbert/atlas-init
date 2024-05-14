VERSION = "VERSION_PLACEHOLDER"


def running_in_repo() -> bool:
    """VERSION is updated during packaging"""
    return VERSION == "VERSION_PLACEHOLDER"