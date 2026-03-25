from __future__ import annotations

import pytest

from atlas_init.cli_tf.api_attributes import (
    collect_resource_api_attributes,
    extract_endpoint_attributes,
    extract_version_headers,
    flatten_schema_paths,
)
from atlas_init.cli_tf.openapi import OpenapiSchema
from atlas_init.cli_tf.sdk_usage import ApiEndpoint, ResourceEndpoints, SourceKind

ENV_TF_PROVIDER_PATH = "TF_PROVIDER_PATH"


def _make_spec(schemas: dict, paths: dict | None = None) -> OpenapiSchema:
    return OpenapiSchema(
        openapi="3.0.0",
        info={"title": "test", "version": "1.0"},
        paths=paths or {},
        components={"schemas": schemas},
    )


INLINE_SCHEMAS: dict = {
    "HardwareSpec": {
        "type": "object",
        "properties": {
            "diskSizeGB": {"type": "number", "format": "double"},
            "diskIOPS": {"type": "integer"},
            "ebsVolumeType": {"type": "string", "readOnly": True},
            "instanceSize": {"type": "string"},
            "nodeCount": {"type": "integer"},
        },
    },
    "RegionConfig": {
        "type": "object",
        "properties": {
            "regionName": {"type": "string"},
            "electableSpecs": {"$ref": "#/components/schemas/HardwareSpec"},
            "priority": {"type": "integer"},
        },
    },
    "ReplicationSpec": {
        "type": "object",
        "properties": {
            "zoneName": {"type": "string"},
            "regionConfigs": {"type": "array", "items": {"$ref": "#/components/schemas/RegionConfig"}},
        },
    },
    "ClusterDescription": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "clusterType": {"type": "string"},
            "replicationSpecs": {"type": "array", "items": {"$ref": "#/components/schemas/ReplicationSpec"}},
            "tags": {"type": "array", "items": {"type": "string"}},
            "labels": {"type": "object", "additionalProperties": {"type": "string"}},
        },
    },
    "CircularA": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "child": {"$ref": "#/components/schemas/CircularB"},
        },
    },
    "CircularB": {
        "type": "object",
        "properties": {
            "value": {"type": "integer"},
            "parent": {"$ref": "#/components/schemas/CircularA"},
        },
    },
    "AllOfExample": {
        "allOf": [
            {"$ref": "#/components/schemas/HardwareSpec"},
            {"properties": {"providerName": {"type": "string"}}},
        ],
    },
}


def test_flatten_leaf_properties():
    spec = _make_spec(INLINE_SCHEMAS)
    paths = flatten_schema_paths(spec, "#/components/schemas/HardwareSpec")
    assert "diskSizeGB" in paths
    assert "instanceSize" in paths
    assert paths["ebsVolumeType"].read_only


def test_flatten_nested_refs():
    spec = _make_spec(INLINE_SCHEMAS)
    paths = flatten_schema_paths(spec, "#/components/schemas/ClusterDescription")
    assert "replicationSpecs[].regionConfigs[].electableSpecs.instanceSize" in paths
    assert "tags[]" in paths
    assert "labels.*" in paths


def test_flatten_circular_ref():
    spec = _make_spec(INLINE_SCHEMAS)
    paths = flatten_schema_paths(spec, "#/components/schemas/CircularA")
    assert "name" in paths
    assert "child.value" in paths
    assert paths["child.parent"].type == "circular_ref"


def test_flatten_allof():
    spec = _make_spec(INLINE_SCHEMAS)
    paths = flatten_schema_paths(spec, "#/components/schemas/AllOfExample")
    assert "diskSizeGB" in paths
    assert "providerName" in paths


VERSIONED_PATHS: dict = {
    "/api/atlas/v2/groups/{groupId}/things": {
        "get": {
            "operationId": "getThing",
            "responses": {
                "200": {
                    "content": {
                        "application/vnd.atlas.2023-01-01+json": {
                            "schema": {"$ref": "#/components/schemas/HardwareSpec"}
                        },
                        "application/vnd.atlas.2024-08-05+json": {
                            "schema": {"$ref": "#/components/schemas/ClusterDescription"}
                        },
                    }
                }
            },
        },
        "post": {
            "operationId": "createThing",
            "requestBody": {
                "content": {
                    "application/vnd.atlas.2024-08-05+json": {"schema": {"$ref": "#/components/schemas/HardwareSpec"}},
                }
            },
            "responses": {
                "201": {
                    "content": {
                        "application/vnd.atlas.2024-08-05+json": {
                            "schema": {"$ref": "#/components/schemas/ClusterDescription"}
                        },
                    }
                }
            },
        },
    },
}


def test_extract_endpoint_get_latest_version():
    spec = _make_spec(INLINE_SCHEMAS, VERSIONED_PATHS)
    attrs = extract_endpoint_attributes(spec, "/api/atlas/v2/groups/{groupId}/things", "get")
    assert not attrs.request_paths
    assert "replicationSpecs[].regionConfigs[].electableSpecs.instanceSize" in attrs.response_paths


def test_extract_endpoint_explicit_version():
    spec = _make_spec(INLINE_SCHEMAS, VERSIONED_PATHS)
    attrs = extract_endpoint_attributes(
        spec,
        "/api/atlas/v2/groups/{groupId}/things",
        "get",
        version_header="application/vnd.atlas.2023-01-01+json",
    )
    assert "diskSizeGB" in attrs.response_paths
    assert "replicationSpecs[].regionConfigs[].electableSpecs.instanceSize" not in attrs.response_paths


def test_extract_endpoint_post_has_request_and_response():
    spec = _make_spec(INLINE_SCHEMAS, VERSIONED_PATHS)
    attrs = extract_endpoint_attributes(spec, "/api/atlas/v2/groups/{groupId}/things", "post")
    assert "diskSizeGB" in attrs.request_paths
    assert "replicationSpecs[].regionConfigs[].electableSpecs.instanceSize" in attrs.response_paths


def test_collect_resource_api_attributes():
    spec = _make_spec(INLINE_SCHEMAS, VERSIONED_PATHS)
    re_ = ResourceEndpoints(
        resource_type="mongodbatlas_thing",
        source=SourceKind.codegen,
        endpoints=[
            ApiEndpoint(path="/api/atlas/v2/groups/{groupId}/things", method="GET", operation_id="getThing"),
            ApiEndpoint(path="/api/atlas/v2/groups/{groupId}/things", method="POST", operation_id="createThing"),
        ],
    )
    result = collect_resource_api_attributes(spec, re_)
    assert result.all_request_paths
    assert result.all_response_paths
    assert result.all_paths == result.all_request_paths | result.all_response_paths


def test_extract_version_headers(tmp_path):
    config = tmp_path / "config.yml"
    config.write_text(
        "resources:\n"
        "  cluster_api:\n"
        "    version_header: 'application/vnd.atlas.2024-08-05+json'\n"
        "    read:\n"
        "      path: /api/atlas/v2/groups/{groupId}/clusters/{name}\n"
        "      method: GET\n"
        "  project_api:\n"
        "    version_header: 'application/vnd.atlas.2023-01-01+json'\n"
        "    read:\n"
        "      path: /api/atlas/v2/groups/{groupId}\n"
        "      method: GET\n"
    )
    headers = extract_version_headers(config)
    assert headers["mongodbatlas_cluster_api"] == "application/vnd.atlas.2024-08-05+json"
    assert headers["mongodbatlas_project_api"] == "application/vnd.atlas.2023-01-01+json"


def test_flatten_with_real_spec(openapi_schema):
    """Uses the test_data admin_api.yaml fixture to verify against a real-ish spec."""
    schemas = openapi_schema.components.get("schemas", {})
    ref_with_properties = ""
    for name, schema in schemas.items():
        if isinstance(schema, dict) and schema.get("properties"):
            ref_with_properties = f"#/components/schemas/{name}"
            break
    if not ref_with_properties:
        pytest.skip("no schema with properties in test data")
    paths = flatten_schema_paths(openapi_schema, ref_with_properties)
    assert paths
