import os
from pathlib import Path

import dotenv


def current_dir():
    return Path(os.path.curdir).absolute()


REPO_PATH = Path(__file__).parent.parent.parent.parent


def as_profile_dir(name: str) -> Path:
    return REPO_PATH / f"profiles/{name}"


TF_DIR = REPO_PATH / "tf"
CONFIG_PATH = REPO_PATH / "atlas_init.yaml"


def env_file_manual_profile(name: str) -> Path:
    return as_profile_dir(name) / ".env_manual"


def load_dotenv(env_path: Path) -> dict[str, str]:
    return {k: v for k, v in dotenv.dotenv_values(env_path).items() if v}


def dump_vscode_dotenv(generated_path: Path, vscode_env_path: Path) -> None:
    vscode_env_vars = load_dotenv(generated_path)
    vscode_env_vars.pop(
        "TF_CLI_CONFIG_FILE", None
    )  # migration tests will use local provider instead of online
    vscode_env_path.write_text("")
    for k, v in vscode_env_vars.items():
        dotenv.set_key(vscode_env_path, k, v)


def repo_path_rel_path() -> tuple[Path, str]:
    cwd = current_dir()
    rel_path = []
    for path in [cwd, *cwd.parents]:
        if (path / ".git").exists():
            return path, "/".join(reversed(rel_path))
        rel_path.append(path.name)
    raise CwdIsNoRepoPathError("no repo path found from cwd")


class CwdIsNoRepoPathError(ValueError):
    pass
