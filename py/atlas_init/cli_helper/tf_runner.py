import logging
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from zero_3rdparty.file_utils import copy, iter_paths_and_relative

from atlas_init.cli_helper.run import find_binary_on_path, run_command_is_ok
from atlas_init.settings.config import TerraformVars, TestSuite
from atlas_init.settings.env_vars import AtlasInitSettings

logger = logging.getLogger(__name__)


def get_tf_vars(settings: AtlasInitSettings, active_groups: list[TestSuite]) -> dict[str, Any]:
    tf_vars = TerraformVars()
    tf_vars = sum((group.vars for group in active_groups), start=tf_vars)
    return {
        "atlas_public_key": settings.MONGODB_ATLAS_PUBLIC_KEY,
        "atlas_private_key": settings.MONGODB_ATLAS_PRIVATE_KEY,
        "org_id": settings.MONGODB_ATLAS_ORG_ID,
        "aws_region": settings.AWS_REGION,
        "project_name": settings.project_name,
        "out_dir": settings.profile_dir,
        "extra_env_vars": settings.manual_env_vars,
        **settings.cfn_config(),
        **tf_vars.as_configs(),
    }


class TerraformRunError(Exception):
    pass


@dataclass
class state_copier:  # noqa: N801
    profile_path: Path
    tf_path: Path

    @property
    def state_path(self) -> Path:
        return self.profile_path / "tf_state"

    def __enter__(self):
        for state_path, rel_path in iter_paths_and_relative(self.state_path, "terraform.tfstate*", rglob=False):
            copy(state_path, self.tf_path / rel_path)

    def __exit__(self, *_):
        for state_path, rel_path in iter_paths_and_relative(self.tf_path, "terraform.tfstate*", rglob=False):
            state_path.rename(self.state_path / rel_path)


def run_terraform(settings: AtlasInitSettings, command: str, extra_args: list[str]):
    with state_copier(settings.profile_dir, settings.tf_path):
        _run_terraform(settings, command, extra_args)


def _run_terraform(settings: AtlasInitSettings, command: str, extra_args: list[str]):
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
        cwd=settings.tf_path,
        logger=logger,
    )
    if not is_ok:
        raise TerraformRunError
    if settings.skip_copy:
        return
    env_generated = settings.env_vars_generated
    if env_generated.exists():
        clipboard_content = "\n".join(f"export {line}" for line in env_generated.read_text().splitlines())
        pb_binary = find_binary_on_path("pbcopy", logger, allow_missing=True)
        if not pb_binary:
            return
        subprocess.run(pb_binary, text=True, input=clipboard_content, check=True)
        logger.info("loaded env-vars to clipboard ✅")
