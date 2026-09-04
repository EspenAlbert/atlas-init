from __future__ import annotations

import logging
import re
from enum import StrEnum
from pathlib import Path

from model_lib import Entity, dump, parse
from model_lib.serialize.yaml_serialize import allow_duplicate_anchors
from pydantic import Field

from atlas_init.cli_tf.openapi import OpenapiSchema, extract_api_version_content_header
from atlas_init.repos.go_sdk import api_spec_path_transformed
from atlas_init.repos.path import find_resource_dirs

logger = logging.getLogger(__name__)

SDK_CALL_PATTERN = re.compile(r"(?:connV2|\.AtlasV2|\.Client\.AtlasV2)\.(?P<api_group>\w+)\.(?P<method>\w+)\(")
LEGACY_SDK_CALL_PATTERN = re.compile(r"conn\.(?P<api_group>\w+)\.(?P<method>\w+)\(")
RESOURCE_NAME_PATTERN = re.compile(r'resourceName\s*=\s*"(?P<name>[a-z_]+)"')
SDK_IMPORT_PATTERN = re.compile(r'(?:\w+\s+)?"go\.mongodb\.org/atlas-sdk/v(?P<version>\d{11})/admin"')
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
    version: str = ""
    file_path: str = ""
    line_number: int = 0


class CodegenEndpoint(Entity):
    path: str
    method: str
    operation: str
    version: str = ""


class ApiEndpoint(Entity):
    path: str
    method: str
    operation_id: str
    version: str = ""


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
        version = ""
        if version_header := resource_cfg.get("version_header"):
            version = extract_api_version_content_header(str(version_header)) or ""
        endpoints: list[CodegenEndpoint] = []
        for op in CODEGEN_CRUD_OPERATIONS:
            if op_cfg := resource_cfg.get(op):
                if isinstance(op_cfg, dict) and "path" in op_cfg and "method" in op_cfg:
                    endpoints.append(
                        CodegenEndpoint(
                            path=op_cfg["path"], method=op_cfg["method"].upper(), operation=op, version=version
                        )
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


def sdk_version_to_date(sdk_version: str) -> str:
    """Converts e.g. 'v20241023001' or '20241023001' to '2024-10-23'."""
    digits = sdk_version.lstrip("v")
    if len(digits) != 11:
        return ""
    return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"


def _extract_sdk_import_version(text: str) -> str:
    if match := SDK_IMPORT_PATTERN.search(text):
        return sdk_version_to_date(match.group("version"))
    return ""


def _scan_go_file_sdk_calls(path: Path, base_path: Path | None = None) -> list[SdkCall]:
    text = path.read_text()
    version = _extract_sdk_import_version(text)
    rel_path = str(path.relative_to(base_path)) if base_path else path.name
    calls: list[SdkCall] = []
    seen: set[tuple[str, str, bool]] = set()
    for line_nr, line in enumerate(text.splitlines(), 1):
        for match in SDK_CALL_PATTERN.finditer(line):
            key = (match.group("api_group"), match.group("method"), False)
            if key not in seen:
                seen.add(key)
                calls.append(
                    SdkCall(
                        api_group=key[0],
                        method_name=key[1],
                        version=version,
                        file_path=rel_path,
                        line_number=line_nr,
                    )
                )
        for match in LEGACY_SDK_CALL_PATTERN.finditer(line):
            key = (match.group("api_group"), match.group("method"), True)
            if key not in seen:
                seen.add(key)
                calls.append(
                    SdkCall(
                        api_group=key[0],
                        method_name=key[1],
                        legacy=True,
                        file_path=rel_path,
                        line_number=line_nr,
                    )
                )
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
            all_calls.extend(_scan_go_file_sdk_calls(go_file, base_path=service_path))
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


def _extract_latest_version(spec: OpenapiSchema, method_dict: dict) -> str:
    responses = method_dict.get("responses", {})
    for code in ("200", "201"):
        if response := responses.get(code):
            if versions := spec._unpack_schema_versions(response):
                return str(max(versions))
    return ""


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
                    version=_extract_latest_version(spec, method_dict),
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
                resolved_ep = operation_index.get(op_id)
                version = resolved_ep.version if resolved_ep else ce.version
                endpoints.append(ApiEndpoint(path=ce.path, method=ce.method, operation_id=op_id, version=version))

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
                version = ep.version or call.version
                endpoints.append(
                    ApiEndpoint(path=ep.path, method=ep.method, operation_id=ep.operation_id, version=version)
                )
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
