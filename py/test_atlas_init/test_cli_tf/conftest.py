from pathlib import Path
from unittest.mock import MagicMock

import pytest
from github.WorkflowJob import WorkflowJob
from github.WorkflowStep import WorkflowStep
from model_lib import parse_model

from atlas_init.cli_tf.schema_v2 import SchemaV2, parse_schema
from atlas_init.cli_tf.schema_v2_api_parsing import OpenapiSchema, add_api_spec_info


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


@pytest.fixture()
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
