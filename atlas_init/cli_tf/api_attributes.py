from __future__ import annotations

import re
from pathlib import Path

from model_lib import Entity, parse
from model_lib.serialize.yaml_serialize import allow_duplicate_anchors
from pydantic import Field, computed_field

from atlas_init.cli_tf.openapi import OpenapiSchema
from atlas_init.cli_tf.sdk_usage import ResourceEndpoints

VERSION_CONTENT_PATTERN = re.compile(r"application/vnd\.atlas\.(?P<date>[\d-]+)\+json")


class ApiAttributeInfo(Entity):
    name: str
    type: str
    read_only: bool = False
    description: str = ""
    schema_ref: str = ""
    format: str = ""


class EndpointAttributes(Entity):
    path: str
    method: str
    operation_id: str
    request_paths: set[str] = Field(default_factory=set)
    response_paths: set[str] = Field(default_factory=set)


class ResourceApiAttributes(Entity):
    resource_type: str
    endpoints: list[EndpointAttributes] = Field(default_factory=list)

    def simplified_dict(self) -> dict:
        return {
            "resource_type": self.resource_type,
            "all_paths": sorted(self.all_paths)
        }

    @computed_field  # pyright: ignore[reportGeneralTypeIssues]
    @property
    def all_request_paths(self) -> set[str]:
        return {p for ep in self.endpoints for p in ep.request_paths}

    @computed_field  # pyright: ignore[reportGeneralTypeIssues]
    @property
    def all_response_paths(self) -> set[str]:
        return {p for ep in self.endpoints for p in ep.response_paths}

    @computed_field  # pyright: ignore[reportGeneralTypeIssues]
    @property
    def all_paths(self) -> set[str]:
        return self.all_request_paths | self.all_response_paths


class ApiAttributeReport(Entity):
    provider: str
    spec_source: str
    resources: list[ResourceApiAttributes] = Field(default_factory=list)

    def simplified_dict(self) -> dict:
        return {
            "provider": self.provider,
            "spec_source": self.spec_source,
            "resources": [ra.simplified_dict() for ra in self.resources],
        }


def flatten_schema_paths(
    spec: OpenapiSchema,
    schema_ref: str,
    *,
    prefix: str = "",
    max_depth: int = 10,
    _visited: set[str] | None = None,
) -> dict[str, ApiAttributeInfo]:
    if max_depth <= 0:
        return {}
    visited = _visited if _visited is not None else set()
    if schema_ref in visited:
        return {prefix: ApiAttributeInfo(name=prefix, type="circular_ref")} if prefix else {}
    visited.add(schema_ref)

    schema_dict = spec.resolve_ref(schema_ref)
    merged_props = _merge_properties(spec, schema_dict, visited, max_depth)

    result: dict[str, ApiAttributeInfo] = {}
    required_names = set(schema_dict.get("required", []))
    for prop_name, prop in merged_props.items():
        full_path = f"{prefix}.{prop_name}" if prefix else prop_name
        _collect_property_paths(spec, prop, full_path, prop_name, required_names, result, visited, max_depth)
    return result


def _merge_properties(
    spec: OpenapiSchema,
    schema_dict: dict,
    visited: set[str],
    max_depth: int,
) -> dict[str, dict]:
    props: dict[str, dict] = dict(schema_dict.get("properties", {}))
    for entry in schema_dict.get("allOf", []):
        if ref := entry.get("$ref"):
            resolved = spec.resolve_ref(ref)
            props.update(resolved.get("properties", {}))
        else:
            props.update(entry.get("properties", {}))
    return props


def _collect_property_paths(
    spec: OpenapiSchema,
    prop: dict,
    full_path: str,
    prop_name: str,
    required_names: set[str],
    result: dict[str, ApiAttributeInfo],
    visited: set[str],
    max_depth: int,
) -> None:
    read_only = prop.get("readOnly", False)
    description = prop.get("description", "")
    prop_format = prop.get("format", "")
    prop_type = prop.get("type", "")

    if ref := prop.get("$ref"):
        nested = flatten_schema_paths(spec, ref, prefix=full_path, max_depth=max_depth - 1, _visited=visited)
        result.update(nested)
        return

    if prop_type == "array":
        items = prop.get("items", {})
        array_path = f"{full_path}[]"
        if items_ref := items.get("$ref"):
            nested = flatten_schema_paths(spec, items_ref, prefix=array_path, max_depth=max_depth - 1, _visited=visited)
            result.update(nested)
        else:
            result[array_path] = ApiAttributeInfo(
                name=array_path,
                type=f"array<{items.get('type', 'unknown')}>",
                read_only=read_only,
                description=description,
                format=prop_format,
            )
        return

    if prop_type == "object" and "properties" in prop:
        nested_props: dict[str, dict] = prop["properties"]
        nested_required = set(prop.get("required", []))
        for nested_name, nested_prop in nested_props.items():
            nested_path = f"{full_path}.{nested_name}"
            _collect_property_paths(
                spec, nested_prop, nested_path, nested_name, nested_required, result, visited, max_depth - 1
            )
        return

    if prop.get("additionalProperties"):
        result[f"{full_path}.*"] = ApiAttributeInfo(
            name=f"{full_path}.*",
            type="object",
            read_only=read_only,
            description=description,
            format=prop_format,
        )
        return

    result[full_path] = ApiAttributeInfo(
        name=full_path,
        type=prop_type or "unknown",
        read_only=read_only,
        description=description,
        schema_ref=prop.get("$ref", ""),
        format=prop_format,
    )


def _select_versioned_ref(content: dict, version_header: str | None) -> str:
    if version_header and version_header in content:
        return content[version_header].get("schema", {}).get("$ref", "")
    best_date = ""
    best_ref = ""
    for content_type, value in content.items():
        if not isinstance(value, dict):
            continue
        if match := VERSION_CONTENT_PATTERN.match(content_type):
            date = match.group("date")
            if date > best_date:
                best_date = date
                best_ref = value.get("schema", {}).get("$ref", "")
        elif content_type.endswith("json"):
            best_ref = best_ref or value.get("schema", {}).get("$ref", "")
    return best_ref


def extract_endpoint_attributes(
    spec: OpenapiSchema,
    path: str,
    method: str,
    version_header: str | None = None,
) -> EndpointAttributes:
    path_dict = spec.paths.get(path, {})
    operation = path_dict.get(method.lower(), {})
    operation_id = operation.get("operationId", "")

    request_paths: set[str] = set()
    if request_body := operation.get("requestBody"):
        content = request_body.get("content", {})
        if ref := _select_versioned_ref(content, version_header):
            request_paths = set(flatten_schema_paths(spec, ref))

    response_paths: set[str] = set()
    for code in ("200", "201"):
        if response := operation.get("responses", {}).get(code):
            content = response.get("content", {})
            if ref := _select_versioned_ref(content, version_header):
                response_paths = set(flatten_schema_paths(spec, ref))
                break

    return EndpointAttributes(
        path=path,
        method=method.upper(),
        operation_id=operation_id,
        request_paths=request_paths,
        response_paths=response_paths,
    )


def collect_resource_api_attributes(
    spec: OpenapiSchema,
    resource_endpoints: ResourceEndpoints,
    version_header: str | None = None,
) -> ResourceApiAttributes:
    ep_attrs = [
        extract_endpoint_attributes(spec, ep.path, ep.method, version_header) for ep in resource_endpoints.endpoints
    ]
    return ResourceApiAttributes(resource_type=resource_endpoints.resource_type, endpoints=ep_attrs)


def generate_api_attribute_report(
    spec_path: Path,
    resource_endpoints_list: list[ResourceEndpoints],
    version_headers: dict[str, str] | None = None,
) -> ApiAttributeReport:
    spec = parse.parse_model(spec_path, t=OpenapiSchema)
    version_headers = version_headers or {}
    resources = [
        collect_resource_api_attributes(spec, re_, version_headers.get(re_.resource_type))
        for re_ in resource_endpoints_list
    ]
    return ApiAttributeReport(provider="mongodbatlas", spec_source=str(spec_path), resources=resources)


def extract_version_headers(config_path: Path) -> dict[str, str]:
    with allow_duplicate_anchors():
        raw: dict = parse.parse_dict(config_path)
    resources_dict: dict = raw.get("resources", {})
    headers: dict[str, str] = {}
    for key, resource_cfg in resources_dict.items():
        if not isinstance(resource_cfg, dict):
            continue
        if version_header := resource_cfg.get("version_header"):
            headers[f"mongodbatlas_{key}"] = version_header
    return headers
