import logging
import os
from collections.abc import Callable
from pathlib import Path

import dotenv
from appdirs import user_data_dir
from zero_3rdparty.file_utils import ensure_parents_write_text

from atlas_init import running_in_repo

logger = logging.getLogger(__name__)
"""WARNING these variables should only be used through the AtlasInitSettings, not directly"""
if running_in_repo():
    ROOT_PATH = Path(__file__).parent.parent.parent  # atlas_init REPO_PATH
else:
    ROOT_PATH = Path(__file__).parent.parent  # site package install directory
    _default_profiles_path = os.environ.get("ATLAS_INIT_PROFILES_PATH")
    if not _default_profiles_path:
        _default_profiles_path = Path(user_data_dir("atlas_init")) / "profiles"
        warning_msg = f"os.environ['ATLAS_INIT_PROFILES_PATH'] is not set using default: {_default_profiles_path}"
        logger.warning(warning_msg)
DEFAULT_TF_SRC_PATH = ROOT_PATH / "tf"
DEFAULT_ATLAS_INIT_CONFIG_PATH = ROOT_PATH / "atlas_init.yaml"
DEFAULT_ATLAS_INIT_SCHEMA_CONFIG_PATH = ROOT_PATH / "terraform.yaml"


def load_dotenv(env_path: Path) -> dict[str, str]:
    return {k: v for k, v in dotenv.dotenv_values(env_path).items() if v}


def dump_vscode_dotenv(generated_path: Path, vscode_env_path: Path, **extras: str) -> None:
    vscode_env_vars = load_dotenv(generated_path)
    vscode_env_vars.pop("TF_CLI_CONFIG_FILE", None)  # migration tests will use local provider instead of online
    vscode_env_vars.update(extras)
    dump_dotenv(vscode_env_path, vscode_env_vars)


def dump_dotenv(path: Path, env_vars: dict[str, str]):
    ensure_parents_write_text(path, "")
    for k, v in env_vars.items():
        dotenv.set_key(path, k, v)


def current_dir():
    return Path(os.path.curdir).absolute()


def default_factory_cwd(rel_path: str) -> Callable[[], Path]:
    def default_factory():
        return current_dir() / rel_path

    return default_factory


def repo_path_rel_path() -> tuple[Path, str]:
    cwd = current_dir()
    rel_path = []
    for path in [cwd, *cwd.parents]:
        if (path / ".git").exists():
            return path, "/".join(reversed(rel_path))
        rel_path.append(path.name)
    msg = "no repo path found from cwd"
    raise CwdIsNoRepoPathError(msg)


class CwdIsNoRepoPathError(ValueError):
    pass
