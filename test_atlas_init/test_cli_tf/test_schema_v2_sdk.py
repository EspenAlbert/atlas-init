import pytest

from atlas_init.cli_tf.schema_v2 import SchemaV2, SDKModelExample
from atlas_init.cli_tf.schema_v2_sdk import generate_model_go, parse_sdk_model


def test_parse_sdk_model(sdk_repo_path):
    sdk_model = parse_sdk_model(sdk_repo_path, "ApiAtlasResourcePolicy")
    assert sorted(sdk_model.attributes) == [
        "CreatedByUser",
        "CreatedDate",
        "Id",
        "LastUpdatedByUser",
        "LastUpdatedDate",
        "Name",
        "OrgId",
        "Policies",
        "Version",
    ]
    assert [attr.struct_name for attr in sdk_model.attributes.values()] == [
        "CreatedByUser",
        "CreatedDate",
        "Id",
        "LastUpdatedByUser",
        "LastUpdatedDate",
        "Name",
        "OrgId",
        "Policies",
        "Version",
    ]
    assert [attr.json_name for attr in sdk_model.attributes.values()] == [
        "createdByUser",
        "createdDate",
        "id",
        "lastUpdatedByUser",
        "lastUpdatedDate",
        "name",
        "orgId",
        "policies",
        "version",
    ]
    assert {attr.struct_name: attr.struct_type_name for attr in sdk_model.attributes.values() if attr.is_nested} == {
        "CreatedByUser": "ApiAtlasUserMetadata",
        "LastUpdatedByUser": "ApiAtlasUserMetadata",
        "Policies": "ApiAtlasPolicy",
    }
    created_by_user = sdk_model.attributes["CreatedByUser"]
    assert created_by_user.is_nested
    assert sorted(created_by_user.nested_attributes) == ["Id", "Name"]
    policies = sdk_model.attributes["Policies"]
    assert policies.is_nested
    assert sorted(policies.nested_attributes) == ["Body", "Id"]


def test_model_conversion(schema_v2):
    resource = schema_v2.resources["resource_policy"]
    assert resource.conversion.sdk_start_refs == [
        SDKModelExample(
            name="ApiAtlasResourcePolicy",
            examples=["resource_policy_clusterForbidCloudProvider.json"],
        )
    ]


@pytest.mark.parametrize("resource_name", ["resource_policy"])
def test_model_go(sdk_repo_path, schema_with_api_info: SchemaV2, resource_name, file_regression):
    schema = schema_with_api_info
    sdk_model = parse_sdk_model(sdk_repo_path, schema.resources[resource_name].conversion.sdk_start_refs[0].name)
    actual = generate_model_go(schema, schema.resources[resource_name], sdk_model)
    file_regression.check(actual, basename=resource_name, extension=".go")
