import os
from pathlib import Path
from model_lib import dump, parse_model, parse_payload
import pytest
from atlas_init.cli_tf.schema_v2 import SchemaV2
from atlas_init.cli_tf.schema_v2_api_parsing import OpenapiSchema, parse_api_spec_param


def test_openapi_schema_create_parameters(
    schema_v2: SchemaV2, openapi_schema: OpenapiSchema
):
    processor = schema_v2.resources["stream_processor"]
    create_path, read_path = processor.paths
    create_method = openapi_schema.create_method(create_path)
    assert create_method
    assert openapi_schema.read_method(read_path)
    create_path_params = create_method.get("parameters", [])
    assert len(create_path_params) == 2
    group_id_param, tenant_name_param = create_path_params
    assert group_id_param == {"$ref": "#/components/parameters/groupId"}
    project_id_param = parse_api_spec_param(openapi_schema, group_id_param, processor)
    assert project_id_param
    assert project_id_param.name == "project_id"
    assert project_id_param.type == "string"
    assert project_id_param.description
    assert project_id_param.is_required
    assert tenant_name_param == {
        "description": "Human-readable label that identifies the stream instance.",
        "in": "path",
        "name": "tenantName",
        "required": True,
        "schema": {"type": "string"},
    }
    instance_name_param = parse_api_spec_param(
        openapi_schema, tenant_name_param, processor
    )
    assert instance_name_param
    assert instance_name_param.name == "instance_name"
    assert instance_name_param.type == "string"
    assert instance_name_param.description
    assert instance_name_param.is_required

    req_ref = openapi_schema.method_request_body_ref(create_method)
    assert req_ref == "#/components/schemas/StreamsProcessor"
    property_dicts = list(openapi_schema.schema_properties(req_ref))
    assert property_dicts
    assert sorted(d["name"] for d in property_dicts) == [
        "_id",
        "links",
        "name",
        "options",
        "pipeline",
    ]


def test_openapi_schema_read_parameters(schema_v2, openapi_schema: OpenapiSchema):
    processor = schema_v2.resources["stream_processor"]
    read_path = processor.paths[1]
    read_method = openapi_schema.read_method(read_path)
    assert read_method
    read_path_params = read_method.get("parameters", [])
    assert len(read_path_params) == 3
    group_id_param, tenant_name_param, processor_name_param = read_path_params
    assert group_id_param == {"$ref": "#/components/parameters/groupId"}
    assert tenant_name_param["name"] == "tenantName"
    assert processor_name_param["name"] == "processorName"

    response_ref = openapi_schema.method_response_ref(read_method)
    assert response_ref == "#/components/schemas/StreamsProcessorWithStats"
    property_dicts = list(openapi_schema.schema_properties(response_ref))
    assert property_dicts
    assert sorted(d["name"] for d in property_dicts) == [
        "_id",
        "links",
        "name",
        "pipeline",
        "state",
        "stats",
    ]


def test_openapi_schema_read_parameters_array(schema_v2, openapi_schema: OpenapiSchema):
    resource_policy = schema_v2.resources["resource_policy"]
    assert resource_policy
    ref = "#/components/schemas/ApiAtlasResourcePolicyCreateView"
    schema_properties = list(openapi_schema.schema_properties(ref))
    assert sorted(d["name"] for d in schema_properties) == [
        "name",
        "policies",
    ]
    policies = [d for d in schema_properties if d["name"] == "policies"][0]
    schema_attribute = parse_api_spec_param(openapi_schema, policies, resource_policy)
    assert schema_attribute, "unable to infer attribute for policies"
    assert schema_attribute.type == "array"
    assert (
        schema_attribute.schema_ref == "#/components/schemas/ApiAtlasPolicyCreateView"
    )
    assert schema_attribute.is_nested


@pytest.mark.skipif(
    os.environ.get("API_SPEC_PATH", "") == "", reason="needs os.environ[API_SPEC_PATH]"
)
def test_print_out_paths_in_yaml(schema_v2):
    api_path = Path(os.environ["API_SPEC_PATH"])
    parsed_raw = parse_payload(api_path, "json")
    spec_yaml = dump(parsed_raw, "yaml")
    api_path.with_name(f"{api_path.stem}.yaml").write_text(spec_yaml)
    openapi_schema = parse_model(api_path, t=OpenapiSchema)
    for resource in schema_v2.resources.values():
        for path in resource.paths:
            spec_path = openapi_schema.paths[path]
            spec_path_yaml = dump(spec_path, "yaml")
            print(f"content of: {path}")
            print(spec_path_yaml)
