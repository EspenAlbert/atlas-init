import logging
from shutil import copy

from model_lib import dump
from rich.logging import RichHandler

from atlas_init.env_vars import AtlasInitCommand, AtlasInitSettings
from atlas_init.git_utils import owner_project_name
from atlas_init.go import run_go_tests
from atlas_init.tf_vars import get_tf_vars, run_terraform

logger = logging.getLogger(__name__)


def run():
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(rich_tracebacks=True)],
    )
    settings = AtlasInitSettings.safe_settings()
    config = settings.config
    repo_path, rel_path = settings.repo_path_rel_path
    repo_url_path = owner_project_name(repo_path)
    repo_alias = config.repo_alias(repo_url_path)
    logger.info(
        f"repo_alias={repo_alias}, repo_path={repo_path}, repo_url_path={repo_url_path}"
    )
    active_groups = config.active_change_groups(repo_alias, [rel_path])
    if not active_groups:
        logger.warning(f"no active groups for {rel_path}")
        return

    if settings.is_terraform_command:
        tf_vars = get_tf_vars(settings, active_groups)

        tf_vars_path = settings.tf_vars_path
        tf_vars_path.parent.mkdir(exist_ok=True, parents=True)
        tf_vars_str = dump(tf_vars, "pretty_json")
        logger.info(f"writing tf vars to {tf_vars_path}: \n{tf_vars_str}")

        tf_vars_path.write_text(tf_vars_str)
        run_terraform(settings)
        copy(settings.env_vars_generated, settings.env_vars_vs_code)
        logger.info(f"your .env file is ready @ {settings.env_vars_vs_code}")
    elif settings.command == AtlasInitCommand.TEST_GO:
        logger.info("running go tests")
        package_prefix = config.go_package_prefix(repo_alias)
        run_go_tests(repo_path, repo_alias, package_prefix, settings, active_groups)

    else:
        raise NotImplementedError


if __name__ == "__main__":
    run()
