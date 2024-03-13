from atlas_init.env_vars import REPO_PATH
from atlas_init.git_utils import find_active_change_groups


def test_dirty_repo():
    find_active_change_groups(REPO_PATH, "r1", [])