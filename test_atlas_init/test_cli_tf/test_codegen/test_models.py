import os
from pathlib import Path

import pytest
from model_lib import dump, parse_model

from atlas_init.cli_tf.codegen.models import ApiResourcesConfig
from atlas_init.cli_tf.codegen.openapi_minimal import minimal_api_spec_simplified


@pytest.fixture()
def tf_api_resources_config() -> ApiResourcesConfig:
    path = os.environ.get("REPO_PATH_TF", "")
    if not path:
        pytest.skip("REPO_PATH_TF environment variable is not set")
    path = Path(os.environ["REPO_PATH_TF"]) / "tools/codegen/config.yml"
    return parse_model(path, t=ApiResourcesConfig, format="yaml")


def test_parsing_config(tf_api_resources_config: ApiResourcesConfig):
    assert (
        tf_api_resources_config.get_resource("database_user_api").read.path  # type: ignore
        == "/api/atlas/v2/groups/{groupId}/databaseUsers/{databaseName}/{username}"
    )


resources = [
    "custom_db_role_api",
    "database_user_api",
    "push_based_log_export_api",
    "search_deployment_api",
    "project_api",
    "resource_policy_api",
    "stream_instance_api",
    "cluster_api",
]


@pytest.mark.parametrize("resource_name", resources)
def test_create_minimal_api_resources_config(
    tf_api_resources_config: ApiResourcesConfig, file_regression, live_api_spec, resource_name
):
    # print(f"Resources: {tf_api_resources_config.list_resources()}")
    minimal_spec = minimal_api_spec_simplified(tf_api_resources_config.get_resource(resource_name), live_api_spec)
    spec_yaml = dump(minimal_spec, format="yaml")
    file_regression.check(
        spec_yaml,
        extension=".yaml",
        basename=f"api_spec_{resource_name}",
    )
