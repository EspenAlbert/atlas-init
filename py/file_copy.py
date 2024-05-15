import logging
from pathlib import Path
from typing import Any

from hatchling.builders.hooks.plugin.interface import BuildHookInterface
from zero_3rdparty.file_utils import clean_dir, copy, iter_paths_and_relative

REL_PATH_FILES = [
    "atlas_init.yaml",
    "terraform.yaml",
]

PY_PATH = Path(__file__).parent
ATLAS_INIT_PATH = PY_PATH / "atlas_init"
REPO_PATH = PY_PATH.parent
logger = logging.getLogger(__name__)


class CustomBuildHook(BuildHookInterface):
    def initialize(self, version: str, build_data: dict[str, Any]) -> None:
        for rel_path in REL_PATH_FILES:
            copy(REPO_PATH / rel_path, ATLAS_INIT_PATH / rel_path)
        for tf_path, tf_rel_path in iter_paths_and_relative(REPO_PATH / "tf", "*.tf", only_files=True):
            dest_path = ATLAS_INIT_PATH / "tf" / tf_rel_path
            copy(tf_path, dest_path)
        return super().initialize(version, build_data)

    def clean(self, versions: list[str]) -> None:
        for rel_path in REL_PATH_FILES:
            logger.warning(f"will remove again: {rel_path}")
            dest_path = ATLAS_INIT_PATH / rel_path
            if dest_path.exists():
                dest_path.unlink()
        if (ATLAS_INIT_PATH / "tf").exists():
            clean_dir(ATLAS_INIT_PATH / "tf", recreate=False)
        return super().clean(versions)
