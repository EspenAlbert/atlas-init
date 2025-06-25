import logging
from pathlib import Path
from atlas_init.tf_ext.args import REPO_PATH_ARG

logger = logging.getLogger(__name__)


def tf_vars(
    repo_path: Path = REPO_PATH_ARG,
):
    logger.info(f"Analyzing Terraform variables in repository: {repo_path}")
