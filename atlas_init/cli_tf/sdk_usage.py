from __future__ import annotations

import logging
import re
from enum import StrEnum
from pathlib import Path

from model_lib import Entity, dump, parse
from model_lib.serialize.yaml_serialize import allow_duplicate_anchors
from pydantic import Field, computed_field

from atlas_init.cli_tf.openapi import OpenapiSchema
from atlas_init.repos.go_sdk import api_spec_path_transformed
from atlas_init.repos.path import find_resource_dirs

logger = logging.getLogger(__name__)

SDK_CALL_PATTERN = re.compile(r"(?:connV2|\.AtlasV2|\.Client\.AtlasV2)\.(?P<api_group>\w+)\.(?P<method>\w+)\(")
LEGACY_SDK_CALL_PATTERN = re.compile(r"conn\.(?P<api_group>\w+)\.(?P<method>\w+)\(")
RESOURCE_NAME_PATTERN = re.compile(r'resourceName\s*=\s*"(?P<name>[a-z_]+)"')
CODEGEN_CRUD_OPERATIONS = ("read", "create", "update", "delete")

_THIS_FILE = "sdk_usage.py"

# SDK method names that don't match the spec operationId (naming divergence).
# Format: sdk_method_name -> spec_operationId
# To update: check the SDK spec operationIds in openapi/atlas-api-transformed.yaml
SDK_METHOD_ALIASES: dict[str, str] = {
    "listProjectUsers": "listGroupUsers",
    "listOrganizationUsers": "listOrgUsers",
    "getUserByUsername": "getUserByName",
    "createTeam": "createOrgTeam",
    "getTeamById": "getOrgTeam",
    "renameTeam": "renameOrgTeam",
    "deleteTeam": "deleteOrgTeam",
    "removeProjectTeam": "removeGroupTeam",
    "listProjects": "listGroups",
    "listProjectTeams": "listGroupTeams",
}

# SDK methods whose operations were removed from the spec (deprecated APIs).
# These are silently skipped instead of logging warnings.
# To update: check if the operationId exists in openapi/atlas-api-transformed.yaml
KNOWN_MISSING_OPERATIONS: set[str] = {
    "createServerlessInstance",
    "updateServerlessInstance",
    "deleteServerlessInstance",
}

# Packages where neither test files nor resourceName const declare a name.
# Format: dir_name -> resource_name (without mongodbatlas_ prefix)
# To update: check the Go source or Terraform registry for the canonical name
PACKAGE_RESOURCE_NAMES: dict[str, str] = {
    "atlasuser": "atlas_user",
    "controlplaneipaddresses": "control_plane_ip_addresses",
    "projectipaddresses": "project_ip_addresses",
    "rolesorgid": "roles_org_id",
    "serverlessinstance": "serverless_instance",
    "sharedtier": "shared_tier",
}


class SourceKind(StrEnum):
    codegen = "codegen"
    handwritten = "handwritten"


class SdkCall(Entity):
    api_group: str
    method_name: str
    legacy: bool = False


class CodegenEndpoint(Entity):
    path: str
    method: str
    operation: str


class ApiEndpoint(Entity):
    path: str
    method: str
    operation_id: str


class ResourceSdkUsage(Entity):
    resource_type: str
    package_path: str
    source: SourceKind
    sdk_calls: list[SdkCall] = Field(default_factory=list)
    codegen_endpoints: list[CodegenEndpoint] = Field(default_factory=list)


class ResourceEndpoints(Entity):
    resource_type: str
    source: SourceKind
    endpoints: list[ApiEndpoint] = Field(default_factory=list)


class ProviderSdkUsageReport(Entity):
    provider: str
    resources: list[ResourceEndpoints] = Field(default_factory=list)


def parse_codegen_config(config_path: Path) -> list[ResourceSdkUsage]:
    with allow_duplicate_anchors():
        raw: dict = parse.parse_dict(config_path)
    resources_dict: dict = raw.get("resources", {})
    results: list[ResourceSdkUsage] = []
    for key, resource_cfg in resources_dict.items():
        if not isinstance(resource_cfg, dict):
            continue
        endpoints: list[CodegenEndpoint] = []
        for op in CODEGEN_CRUD_OPERATIONS:
            if op_cfg := resource_cfg.get(op):
                if isinstance(op_cfg, dict) and "path" in op_cfg and "method" in op_cfg:
                    endpoints.append(
                        CodegenEndpoint(path=op_cfg["path"], method=op_cfg["method"].upper(), operation=op)
                    )
        if endpoints:
            results.append(
                ResourceSdkUsage(
                    resource_type=f"mongodbatlas_{key}",
                    package_path=f"internal/serviceapi/{key}",
                    source=SourceKind.codegen,
                    codegen_endpoints=endpoints,
                )
            )
    return results


def _scan_go_file_sdk_calls(path: Path) -> list[SdkCall]:
    text = path.read_text()
    calls: list[SdkCall] = []
    seen: set[tuple[str, str, bool]] = set()
    for match in SDK_CALL_PATTERN.finditer(text):
        key = (match.group("api_group"), match.group("method"), False)
        if key not in seen:
            seen.add(key)
            calls.append(SdkCall(api_group=key[0], method_name=key[1]))
    for match in LEGACY_SDK_CALL_PATTERN.finditer(text):
        key = (match.group("api_group"), match.group("method"), True)
        if key not in seen:
            seen.add(key)
            calls.append(SdkCall(api_group=key[0], method_name=key[1], legacy=True))
    return calls


def _find_resource_name_const(go_files: list[Path]) -> str:
    for go_file in go_files:
        text = go_file.read_text()
        if match := RESOURCE_NAME_PATTERN.search(text):
            return match.group("name")
    return ""


def scan_handwritten_sdk_calls(service_path: Path) -> list[ResourceSdkUsage]:
    resource_dirs, non_resource_dirs = find_resource_dirs(service_path)
    resource_name_by_dir: dict[str, str] = {}
    for name, pkg_dir in resource_dirs.items():
        resource_name_by_dir[str(pkg_dir)] = name

    all_dirs = {str(d): d for d in service_path.iterdir() if d.is_dir() and d.name != "testdata"}
    results: list[ResourceSdkUsage] = []
    for dir_key, pkg_dir in all_dirs.items():
        go_files = [f for f in pkg_dir.glob("*.go") if not f.name.endswith("_test.go")]
        if not go_files:
            continue
        all_calls: list[SdkCall] = []
        for go_file in go_files:
            all_calls.extend(_scan_go_file_sdk_calls(go_file))
        if not all_calls:
            continue
        resource_type = resource_name_by_dir.get(dir_key, "")
        if not resource_type:
            resource_type = _find_resource_name_const(go_files)
        if not resource_type:
            resource_type = PACKAGE_RESOURCE_NAMES.get(pkg_dir.name, "")
        if resource_type:
            resource_type = f"mongodbatlas_{resource_type}"
        else:
            resource_type = f"mongodbatlas_{pkg_dir.name}"
            logger.warning(
                f"no resource name found for {pkg_dir.name}, using dir name"
                f" (update PACKAGE_RESOURCE_NAMES in {_THIS_FILE})"
            )
        seen: set[tuple[str, str, bool]] = set()
        deduped: list[SdkCall] = []
        for call in all_calls:
            key = (call.api_group, call.method_name, call.legacy)
            if key not in seen:
                seen.add(key)
                deduped.append(call)
        results.append(
            ResourceSdkUsage(
                resource_type=resource_type,
                package_path=f"internal/service/{pkg_dir.name}",
                source=SourceKind.handwritten,
                sdk_calls=deduped,
            )
        )
    return results


def build_operation_index(spec: OpenapiSchema) -> dict[str, ApiEndpoint]:
    index: dict[str, ApiEndpoint] = {}
    for path_template, path_dict in spec.paths.items():
        if not isinstance(path_dict, dict):
            continue
        for http_method, method_dict in path_dict.items():
            if not isinstance(method_dict, dict):
                continue
            if operation_id := method_dict.get("operationId"):
                index[operation_id] = ApiEndpoint(
                    path=path_template,
                    method=http_method.upper(),
                    operation_id=operation_id,
                )
    return index


def _method_name_to_operation_id(method_name: str) -> str:
    name = method_name.removesuffix("WithParams")
    op_id = name[0].lower() + name[1:]
    return SDK_METHOD_ALIASES.get(op_id, op_id)


def resolve_endpoints(
    usages: list[ResourceSdkUsage],
    operation_index: dict[str, ApiEndpoint],
    path_method_index: dict[tuple[str, str], str] | None = None,
) -> list[ResourceEndpoints]:
    if path_method_index is None:
        path_method_index = {(ep.path, ep.method): ep.operation_id for ep in operation_index.values()}

    results: list[ResourceEndpoints] = []
    for usage in usages:
        endpoints: list[ApiEndpoint] = []
        seen_ops: set[str] = set()

        for ce in usage.codegen_endpoints:
            op_id = path_method_index.get((ce.path, ce.method), "")
            if not op_id:
                logger.warning(
                    f"no operationId for codegen endpoint {ce.method} {ce.path}"
                    f" on {usage.resource_type} (update SDK_METHOD_ALIASES in {_THIS_FILE})"
                )
                op_id = f"unknown_{ce.operation}"
            if op_id not in seen_ops:
                seen_ops.add(op_id)
                endpoints.append(ApiEndpoint(path=ce.path, method=ce.method, operation_id=op_id))

        for call in usage.sdk_calls:
            if call.legacy:
                continue
            op_id = _method_name_to_operation_id(call.method_name)
            if op_id in seen_ops:
                continue
            if op_id in KNOWN_MISSING_OPERATIONS:
                continue
            if ep := operation_index.get(op_id):
                seen_ops.add(op_id)
                endpoints.append(ep)
            else:
                logger.warning(
                    f"unresolved SDK call {call.api_group}.{call.method_name} on {usage.resource_type}"
                    f" (update SDK_METHOD_ALIASES or KNOWN_MISSING_OPERATIONS in {_THIS_FILE})"
                )

        results.append(
            ResourceEndpoints(
                resource_type=usage.resource_type,
                source=usage.source,
                endpoints=endpoints,
            )
        )
    return results


def generate_sdk_usage_report(
    provider_repo_path: Path,
    sdk_repo_path: Path,
    output_path: Path,
) -> ProviderSdkUsageReport:
    codegen_config = provider_repo_path / "tools/codegen/config.yml"
    codegen_usages = parse_codegen_config(codegen_config) if codegen_config.exists() else []

    service_path = provider_repo_path / "internal/service"
    handwritten_usages = scan_handwritten_sdk_calls(service_path) if service_path.exists() else []

    spec_path = api_spec_path_transformed(sdk_repo_path)
    spec = parse.parse_model(spec_path, t=OpenapiSchema)
    operation_index = build_operation_index(spec)

    all_usages = codegen_usages + handwritten_usages
    resource_endpoints = resolve_endpoints(all_usages, operation_index)

    report = ProviderSdkUsageReport(provider="mongodbatlas", resources=resource_endpoints)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dump.dump_as_str(report, "pretty_json"))
    logger.info(f"wrote SDK usage report to {output_path} ({len(resource_endpoints)} resources)")
    return report


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
