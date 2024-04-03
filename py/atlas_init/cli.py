import logging
from shutil import copy

from model_lib import dump

from atlas_init.env_vars import AtlasInitCommand, AtlasInitSettings, CwdIsNoRepoPathError
from atlas_init.git_utils import owner_project_name
from atlas_init.go import run_go_tests
from atlas_init.rich_log import configure_logging
from atlas_init.tf_runner import get_tf_vars, run_terraform

logger = logging.getLogger(__name__)


def run():
    configure_logging()
    settings = AtlasInitSettings.safe_settings()
    config = settings.config
    try:
        repo_path, rel_path = settings.repo_path_rel_path
    except CwdIsNoRepoPathError as e:
        logger.warning(repr(e))
        repo_path = repo_alias = rel_path = None
        change_paths = []
    else:
        repo_url_path = owner_project_name(repo_path)
        repo_alias = config.repo_alias(repo_url_path)
        logger.info(
            f"repo_alias={repo_alias}, repo_path={repo_path}, repo_url_path={repo_url_path}"
        )
        change_paths = [rel_path]
    active_suites = config.active_test_suites(
        repo_alias, change_paths, settings.test_suites_parsed
    )
    logger.info(f"active_suites: {[s.name for s in active_suites]}")
    if settings.is_terraform_command:
        tf_vars = get_tf_vars(settings, active_suites)

        tf_vars_path = settings.tf_vars_path
        tf_vars_path.parent.mkdir(exist_ok=True, parents=True)
        tf_vars_str = dump(tf_vars, "pretty_json")
        logger.info(f"writing tf vars to {tf_vars_path}: \n{tf_vars_str}")

        tf_vars_path.write_text(tf_vars_str)
        run_terraform(settings)
        if settings.env_vars_generated.exists():
            copy(settings.env_vars_generated, settings.env_vars_vs_code)
            logger.info(f"your .env file is ready @ {settings.env_vars_vs_code}")
    elif settings.command == AtlasInitCommand.TEST_GO:
        assert repo_alias and repo_path, "cwd must be a repo"
        sorted_suites = sorted(suite.name for suite in active_suites)
        logger.info(f"running go tests for {len(active_suites)} test-suites: {sorted_suites}")
        package_prefix = config.go_package_prefix(repo_alias)
        run_go_tests(repo_path, repo_alias, package_prefix, settings, active_suites)

    else:
        raise NotImplementedError


if __name__ == "__main__":
    run()
