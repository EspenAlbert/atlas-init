import logging

from model_lib import dump
from rich.logging import RichHandler

from atlas_init.env_vars import AtlasInitSettings
from atlas_init.git_utils import owner_project_name
from atlas_init.tf_vars import get_tf_vars, run_command

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
    logger.info(f"repo_path={repo_path}, repo_url_path={repo_url_path}")
    active_groups = config.active_change_groups(repo_url_path, [rel_path])
    if not active_groups:
        logger.warning(f"no active groups for {rel_path}")
        return
    tf_vars = get_tf_vars(settings, active_groups)

    tf_vars_path = settings.tf_vars_path
    tf_vars_path.parent.mkdir(exist_ok=True, parents=True)
    tf_vars_str = dump(tf_vars, "pretty_json")
    logger.info(f"writing tf vars to {tf_vars_path}: \n{tf_vars_str}")

    tf_vars_path.write_text(tf_vars_str)
    run_command(settings)


if __name__ == "__main__":
    run()
