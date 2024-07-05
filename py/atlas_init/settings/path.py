import os
from pathlib import Path

import dotenv
from zero_3rdparty.file_utils import ensure_parents_write_text

from atlas_init import running_in_repo

"""WARNING these variables should only be used through the AtlasInitSettings, not directly"""
if running_in_repo():
    ROOT_PATH = Path(__file__).parent.parent.parent.parent  # atlas_init REPO_PATH
    DEFAULT_PROFILES_PATH = ROOT_PATH / "profiles"
else:
    ROOT_PATH = Path(__file__).parent.parent  # site package install directory
    _default_profiles_path = os.environ.get("ATLAS_INIT_PROFILES_PATH")
    assert (
        _default_profiles_path
    ), "must set os.environ['ATLAS_INIT_PROFILES_PATH'] to a writeable directory for atlas_init to work"
    DEFAULT_PROFILES_PATH = Path(_default_profiles_path)
DEFAULT_PROFILES_PATH.mkdir(exist_ok=True, parents=True)
DEFAULT_TF_PATH = ROOT_PATH / "tf"
DEFAULT_CONFIG_PATH = ROOT_PATH / "atlas_init.yaml"
DEFAULT_SCHEMA_CONFIG_PATH = ROOT_PATH / "terraform.yaml"
DEFAULT_GITHUB_CI_RUN_LOGS = ROOT_PATH / "github_ci_run_logs"


def load_dotenv(env_path: Path) -> dict[str, str]:
    return {k: v for k, v in dotenv.dotenv_values(env_path).items() if v}


def dump_vscode_dotenv(generated_path: Path, vscode_env_path: Path) -> None:
    vscode_env_vars = load_dotenv(generated_path)
    vscode_env_vars.pop("TF_CLI_CONFIG_FILE", None)  # migration tests will use local provider instead of online
    dump_dotenv(vscode_env_path, vscode_env_vars)


def dump_dotenv(path: Path, env_vars: dict[str, str]):
    ensure_parents_write_text(path, "")
    for k, v in env_vars.items():
        dotenv.set_key(path, k, v)


def current_dir():
    return Path(os.path.curdir).absolute()


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
