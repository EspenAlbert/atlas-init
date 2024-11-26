import os
from pathlib import Path

from atlas_init.cli_tf.mock_tf_log import resolve_admin_api_path
import pytest

from atlas_init.settings.env_vars import (
    REQUIRED_FIELDS,
    AtlasInitPaths,
    as_env_var_name,
)
from atlas_init.settings.path import dump_dotenv


@pytest.fixture
def tmp_paths(monkeypatch, tmp_path: Path) -> AtlasInitPaths:  # type: ignore
    profiles_path = as_env_var_name("profiles_path")
    env_before = {**os.environ}
    assert profiles_path == "ATLAS_INIT_PROFILES_PATH"
    monkeypatch.setenv(profiles_path, str(tmp_path))
    yield AtlasInitPaths()  # type: ignore
    os.environ.clear()
    os.environ.update(env_before)


@pytest.fixture(scope="session")
def api_spec_path_transformed() -> Path:
    return resolve_admin_api_path(os.environ.get("SDK_REPO_PATH", ""), "main", "")


def mongodb_atlas_required_vars() -> dict[str, str]:
    return {key: f"value_{key}" for key in REQUIRED_FIELDS}


def write_required_vars(
    paths: AtlasInitPaths,
    env_vars_in_file: dict[str, str] | None = None,
    project_name: str = "",
):
    env_vars_in_file = env_vars_in_file or mongodb_atlas_required_vars()
    if project_name:
        env_vars_in_file[as_env_var_name("project_name")] = project_name
    dump_dotenv(paths.env_file_manual, env_vars_in_file)
