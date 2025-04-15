import os
from pathlib import Path
from typing import Callable
from unittest.mock import MagicMock

import pytest
from github.WorkflowJob import WorkflowJob
from github.WorkflowStep import WorkflowStep
from model_lib import parse_model

from atlas_init.cli_tf.schema_v2 import SchemaV2, parse_schema
from atlas_init.cli_tf.schema_v2_api_parsing import OpenapiSchema, add_api_spec_info
from atlas_init.cli_tf.schema_v3 import ResourceSchemaV3


def as_step(name: str) -> WorkflowStep:
    step = MagicMock(spec=WorkflowStep)
    step.name = name
    return step


@pytest.fixture
def mock_job() -> WorkflowJob:
    return MagicMock(
        spec=WorkflowJob,
        steps=[
            as_step(name="checkout"),
            as_step(name="setup-go"),
            as_step(name="setup-terraform"),
            as_step(name="Acceptance Tests"),
        ],
        html_url="https://github.com/mongodb/terraform-provider-mongodbatlas/actions/runs/9671377861/job/26681936440",
    )


@pytest.fixture
def tf_test_data_dir() -> Path:
    return Path(__file__).parent / "test_data"


@pytest.fixture
def github_ci_logs_dir(tf_test_data_dir) -> Path:
    return tf_test_data_dir / "github_ci_logs"


@pytest.fixture
def schema_v2(tf_test_data_dir) -> SchemaV2:
    return parse_schema(tf_test_data_dir / "schema_v2.yaml")


@pytest.fixture
def api_spec_path(tf_test_data_dir) -> Path:
    return tf_test_data_dir / "admin_api.yaml"


@pytest.fixture
def openapi_schema(api_spec_path) -> OpenapiSchema:
    return parse_model(api_spec_path, t=OpenapiSchema)


@pytest.fixture
def schema_with_api_info(schema_v2, api_spec_path) -> SchemaV2:
    add_api_spec_info(schema_v2, api_spec_path)
    return schema_v2


@pytest.fixture(scope="session")
def sdk_repo_path() -> Path:
    repo_path_str = os.environ.get("SDK_REPO_PATH", "")
    if not repo_path_str:
        pytest.skip("needs os.environ[SDK_REPO_PATH]")
    return Path(repo_path_str)


@pytest.fixture
def parse_resource_v3(spec_resources_v3_paths):
    def parse_resource(resource_name: str) -> ResourceSchemaV3:
        assert resource_name in spec_resources_v3_paths
        spec_path = spec_resources_v3_paths[resource_name]
        return parse_model(spec_path, t=ResourceSchemaV3)
    return parse_resource


@pytest.fixture
def spec_resources_v3_paths(tf_test_data_dir) -> dict[str, Path]:
    resources: dict[str, Path] = {
        yml_path.stem: yml_path
        for yml_path in (tf_test_data_dir / "tf_spec").glob("*.yaml")
    }
    return resources


@pytest.fixture
def go_schema_paths() -> Callable[[], dict[str, Path]]:
    def _go_file_path() -> dict[str, Path]:
        env_var_names = [
            "GO_SCHEMA_SDKv2_PATH",
            "GO_SCHEMA_TPF_PATH",
        ]
        paths = {
            name.removeprefix("GO_SCHEMA_").removesuffix("_PATH"): os.environ.get(
                name, ""
            )
            for name in env_var_names
        }
        missing_paths = {name: path for name, path in paths.items() if path == ""}
        if missing_paths:
            pytest.skip(
                f"needs os.environ[{', '.join(missing_paths.keys())}] {env_var_names}"
            )
        return {name: Path(path) for name, path in paths.items()}

    return _go_file_path
