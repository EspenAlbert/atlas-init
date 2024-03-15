import logging
import os
import subprocess
from typing import Any

from atlas_init.config import TerraformVars, TestSuit
from atlas_init.env_vars import REPO_PATH, AtlasInitSettings
from atlas_init.util import run_command_is_ok

logger = logging.getLogger(__name__)


def get_tf_vars(
    settings: AtlasInitSettings, active_groups: list[TestSuit]
) -> dict[str, Any]:
    tf_vars = (
        sum((group.vars for group in active_groups), start=TerraformVars())
        if len(active_groups) > 1
        else active_groups[0].vars
    )
    external_settings = settings.external_settings
    return {
        "atlas_public_key": external_settings.MONGODB_ATLAS_PUBLIC_KEY,
        "atlas_private_key": external_settings.MONGODB_ATLAS_PRIVATE_KEY,
        "org_id": external_settings.MONGODB_ATLAS_ORG_ID,
        "aws_region": external_settings.AWS_REGION,
        "project_name": settings.project_name,
        "out_dir": settings.out_dir,
        "extra_env_vars": settings.manual_env_vars,
        **settings.cfn_config(),
        **tf_vars.as_configs(),
    }


def run_terraform(settings: AtlasInitSettings):
    command = [
        "terraform",
        settings.command,
        "-var-file",
        str(settings.tf_vars_path),
        *settings.command_args,
    ]
    is_ok = run_command_is_ok(
        command,
        env=os.environ | {"TF_DATA_DIR": settings.tf_data_dir},
        cwd=REPO_PATH / "tf",
        logger=logger,
    )
    assert is_ok, "command failed"
    if settings.skip_copy:
        return
    env_generated = settings.env_vars_generated
    if env_generated.exists():
        clipboard_content = "\n".join(
            f"export {l}" for l in env_generated.read_text().splitlines()
        )
        subprocess.run(
            "pbcopy", universal_newlines=True, input=clipboard_content, check=True
        )
        logger.info("loaded env-vars to clipboard ✅")
