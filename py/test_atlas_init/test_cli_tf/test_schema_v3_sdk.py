import pytest

from atlas_init.cli_tf.schema_v2_sdk import parse_sdk_model
from atlas_init.cli_tf.schema_v3_sdk import generate_model_go, set_name_attribute_overrides

adv_cluster_attr_overrides = {
    "ProjectId": "ProjectID",
    "Id": "ClusterID",
    "MongoDbEmployeeAccessGrant": "MongoDBEmployeeAccessGrant",
    "MongoDbMajorVersion": "MongoDBMajorVersion",
    "MongoDbVersion": "MongoDBVersion",
}
@pytest.mark.parametrize(
    "resource_name,sdk_model,attr_name_overrides", [
        ("resourcepolicy", "ApiAtlasResourcePolicy", {}),
        ("advancedcluster", "ClusterDescription20240805", adv_cluster_attr_overrides),
        ("advancedclusterprocessargs", "ClusterDescriptionProcessArgs20240805", {}),
        ]
)
def test_model_go(
    sdk_repo_path, parse_resource_v3, resource_name, file_regression, sdk_model, attr_name_overrides
):
    set_name_attribute_overrides(attr_name_overrides)
    resource = parse_resource_v3(resource_name)
    parsed_sdk_model = parse_sdk_model(sdk_repo_path, sdk_model)
    actual = generate_model_go(resource, parsed_sdk_model)
    file_regression.check(actual, basename=f"model_from_{sdk_model}", extension=".go")
