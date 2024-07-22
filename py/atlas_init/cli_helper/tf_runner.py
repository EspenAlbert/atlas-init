import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from model_lib import dump
from zero_3rdparty.file_utils import copy, iter_paths_and_relative

from atlas_init.cli_helper.run import (
    add_to_clipboard,
    run_command_is_ok,
    run_command_receive_result,
)
from atlas_init.settings.config import TerraformVars, TestSuite
from atlas_init.settings.env_vars import AtlasInitSettings

logger = logging.getLogger(__name__)


def get_tf_vars(settings: AtlasInitSettings, active_groups: list[TestSuite]) -> dict[str, Any]:  # type: ignore
    tf_vars = TerraformVars()  # type: ignore
    tf_vars = sum((group.vars for group in active_groups), start=tf_vars)
    return {
        "atlas_public_key": settings.MONGODB_ATLAS_PUBLIC_KEY,
        "atlas_private_key": settings.MONGODB_ATLAS_PRIVATE_KEY,
        "atlas_base_url": settings.MONGODB_ATLAS_BASE_URL,
        "is_mongodbgov_cloud": settings.is_mongodbgov_cloud,
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
    state_path: Path
    tf_path: Path

    def __enter__(self):
        self.state_path.mkdir(exist_ok=True, parents=True)
        for state_path, rel_path in iter_paths_and_relative(self.state_path, "terraform.tfstate*", rglob=False):
            copy(state_path, self.tf_path / rel_path)

    def __exit__(self, *_):
        self.tf_path.mkdir(exist_ok=True, parents=True)
        for state_path, rel_path in iter_paths_and_relative(self.tf_path, "terraform.tfstate*", rglob=False):
            state_path.rename(self.state_path / rel_path)


def run_terraform(settings: AtlasInitSettings, command: str, extra_args: list[str]):
    with state_copier(settings.tf_state_path, settings.tf_path):
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
        add_to_clipboard(clipboard_content, logger)
        logger.info("loaded env-vars to clipboard ✅")


def dump_tf_vars(settings: AtlasInitSettings, tf_vars: dict[str, Any]):
    tf_vars_path = settings.tf_vars_path
    tf_vars_path.parent.mkdir(exist_ok=True, parents=True)
    tf_vars_str = dump(tf_vars, "pretty_json")
    logger.info(f"writing tf vars to {tf_vars_path}: \n{tf_vars_str}")
    tf_vars_path.write_text(tf_vars_str)


def export_outputs(settings: AtlasInitSettings) -> None:
    with state_copier(settings.tf_state_path, settings.tf_path):
        result = run_command_receive_result(
            "terraform output -json",
            settings.tf_path,
            logger,
            env=os.environ | {"TF_DATA_DIR": settings.tf_data_dir},
        )
    settings.tf_outputs_path.write_text(result)
