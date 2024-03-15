from atlas_init.env_vars import REPO_PATH
from atlas_init.git_utils import find_active_test_suites


def test_dirty_repo():
    find_active_test_suites(REPO_PATH, "r1", [])
