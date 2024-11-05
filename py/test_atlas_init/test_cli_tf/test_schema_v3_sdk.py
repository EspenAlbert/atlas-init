from atlas_init.cli_tf.schema_v2_sdk import parse_sdk_model
from atlas_init.cli_tf.schema_v3_sdk import generate_model_go
import pytest
from test_atlas_init.test_cli_tf.conftest import parse_resource_v3


@pytest.mark.parametrize(
    "resource_name,sdk_model", [("resourcepolicy", "ApiAtlasResourcePolicy")]
)
def test_model_go(
    sdk_repo_path, spec_resources_v3_paths, resource_name, file_regression, sdk_model
):
    resource = parse_resource_v3(spec_resources_v3_paths, resource_name)
    parsed_sdk_model = parse_sdk_model(sdk_repo_path, sdk_model)
    actual = generate_model_go(resource, parsed_sdk_model)
    file_regression.check(actual, basename=resource_name, extension=".go")
