from atlas_init.env_vars import REPO_PATH


# def find_active_test_suites(repo_path: Path, repo_alias: str, groups: list[TestSuite]):
#     repo = Repo(repo_path)
#     for file in repo.head.commit.stats.files:
#         print(f"changed: {file}")

    # https://gitpython.readthedocs.io/en/stable/quickstart.html
    # if repo.is_dirty:
    #     repo.untracked_files
    #     index = repo.working_dir
    #     diff = index.diff(None)
    #     for (file, _) in diff.index.entries:
    #         print(f"dirty: {file}")
    # else:

def test_dirty_repo():
    raise NotImplementedError
    # find_active_test_suites(REPO_PATH, "r1", [])
