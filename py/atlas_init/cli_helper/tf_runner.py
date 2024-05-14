import logging
import os
import subprocess
from typing import Any

from atlas_init.settings.config import TerraformVars, TestSuite
from atlas_init.settings.env_vars import AtlasInitSettings
from atlas_init.cli_helper.run import run_command_is_ok
from atlas_init.settings.path import TF_DIR

logger = logging.getLogger(__name__)


def get_tf_vars(
    settings: AtlasInitSettings, active_groups: list[TestSuite]
) -> dict[str, Any]:
    tf_vars = TerraformVars()
    tf_vars = sum((group.vars for group in active_groups), start=tf_vars)
    return {
        "atlas_public_key": settings.MONGODB_ATLAS_PUBLIC_KEY,
        "atlas_private_key": settings.MONGODB_ATLAS_PRIVATE_KEY,
        "org_id": settings.MONGODB_ATLAS_ORG_ID,
        "aws_region": settings.AWS_REGION,
        "project_name": settings.project_name,
        "out_dir": settings.out_dir,
        "extra_env_vars": settings.manual_env_vars,
        **settings.cfn_config(),
        **tf_vars.as_configs(),
    }


class TerraformRunError(Exception):
    pass


def run_terraform(settings: AtlasInitSettings, command: str, extra_args: list[str]):
    command_parts = [
        "terraform",
        command,
        "-var-file",
        str(settings.tf_vars_path),
        *extra_args,
    ]
    is_ok = run_command_is_ok(
        command_parts,
        env=os.environ | {"TF_DATA_DIR": settings.tf_data_dir},
        cwd=TF_DIR,
        logger=logger,
    )
    if not is_ok:
        raise TerraformRunError()
    if settings.skip_copy:
        return
    env_generated = settings.env_vars_generated
    if env_generated.exists():
        clipboard_content = "\n".join(
            f"export {line}" for line in env_generated.read_text().splitlines()
        )
        subprocess.run(
            "pbcopy", universal_newlines=True, input=clipboard_content, check=True
        )
        logger.info("loaded env-vars to clipboard ✅")