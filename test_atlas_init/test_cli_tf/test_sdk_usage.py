import os
from pathlib import Path

import pytest

from atlas_init.cli_tf.sdk_usage import (
    ApiEndpoint,
    CodegenEndpoint,
    ResourceSdkUsage,
    SdkCall,
    SourceKind,
    _scan_go_file_sdk_calls,
    build_operation_index,
    generate_sdk_usage_report,
    parse_codegen_config,
    resolve_endpoints,
    scan_handwritten_sdk_calls,
    sdk_version_to_date,
)

ENV_TF_PROVIDER_PATH = "TF_PROVIDER_PATH"


@pytest.fixture(scope="session")
def provider_repo_path() -> Path:
    path_str = os.environ.get(ENV_TF_PROVIDER_PATH, "")
    if not path_str:
        pytest.skip(f"needs os.environ[{ENV_TF_PROVIDER_PATH}]")
    path = Path(path_str)
    assert path.exists(), f"{ENV_TF_PROVIDER_PATH} does not exist: {path}"
    return path


@pytest.fixture(scope="session")
def codegen_config_path(provider_repo_path) -> Path:
    return provider_repo_path / "tools/codegen/config.yml"


@pytest.fixture(scope="session")
def service_path(provider_repo_path) -> Path:
    return provider_repo_path / "internal/service"


def test_parse_codegen_config(codegen_config_path):
    usages = parse_codegen_config(codegen_config_path)
    assert len(usages) >= 20
    project_api = next((u for u in usages if u.resource_type == "mongodbatlas_project_api"), None)
    assert project_api
    methods = {(ep.method, ep.operation) for ep in project_api.codegen_endpoints}
    assert ("GET", "read") in methods
    assert ("POST", "create") in methods
    for usage in usages:
        assert usage.source == SourceKind.codegen
        assert usage.codegen_endpoints


def test_scan_handwritten_sdk_calls(service_path):
    usages = scan_handwritten_sdk_calls(service_path)
    assert len(usages) > 50
    cluster_usage = next((u for u in usages if "advancedcluster" in u.resource_type), None)
    assert cluster_usage
    api_groups = {c.api_group for c in cluster_usage.sdk_calls}
    assert "ClustersApi" in api_groups
    project_usage = next((u for u in usages if u.resource_type == "mongodbatlas_project"), None)
    assert project_usage
    assert any(c.api_group == "ProjectsApi" for c in project_usage.sdk_calls)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("v20241023001", "2024-10-23"),
        ("20240805004", "2024-08-05"),
        ("v20231115008", "2023-11-15"),
        ("short", ""),
    ],
)
def test_sdk_version_to_date(raw, expected):
    assert sdk_version_to_date(raw) == expected


def test_scan_go_file_extracts_version(tmp_path):
    pkg_dir = tmp_path / "cluster"
    pkg_dir.mkdir()
    go_file = pkg_dir / "resource.go"
    go_file.write_text(
        "package cluster\n"
        "import (\n"
        '\t"go.mongodb.org/atlas-sdk/v20241023001/admin"\n'
        ")\n"
        "func read(client *admin.APIClient) {\n"
        "\tclient.AtlasV2.ClustersApi.GetCluster(ctx)\n"
        "}\n"
    )
    calls = _scan_go_file_sdk_calls(go_file, base_path=tmp_path)
    assert len(calls) == 1
    assert calls[0].api_group == "ClustersApi"
    assert calls[0].method_name == "GetCluster"
    assert calls[0].version == "2024-10-23"
    assert calls[0].file_path == "cluster/resource.go"
    assert calls[0].line_number == 6


def test_scan_go_file_aliased_import(tmp_path):
    go_file = tmp_path / "resource.go"
    go_file.write_text(
        "package svc\n"
        "import (\n"
        '\tadmin2 "go.mongodb.org/atlas-sdk/v20240805004/admin"\n'
        ")\n"
        "func create(client *admin2.APIClient) {\n"
        "\tclient.AtlasV2.ProjectsApi.CreateProject(ctx)\n"
        "}\n"
    )
    calls = _scan_go_file_sdk_calls(go_file)
    assert len(calls) == 1
    assert calls[0].version == "2024-08-05"
    assert calls[0].file_path == "resource.go"
    assert calls[0].line_number == 6


def test_scan_go_file_no_sdk_import(tmp_path):
    go_file = tmp_path / "legacy.go"
    go_file.write_text("package legacy\nfunc read(conn *matlas.Client) {\n\tconn.Projects.List(ctx)\n}\n")
    calls = _scan_go_file_sdk_calls(go_file)
    assert len(calls) == 1
    assert calls[0].legacy
    assert calls[0].version == ""
    assert calls[0].file_path == "legacy.go"
    assert calls[0].line_number == 3


def test_build_operation_index(openapi_schema):
    index = build_operation_index(openapi_schema)
    assert len(index) > 0
    for op_id, ep in index.items():
        assert ep.operation_id == op_id
        assert ep.method
        assert ep.path
    versioned = [ep for ep in index.values() if ep.version]
    assert versioned


def test_resolve_endpoints():
    operation_index = {
        "getCluster": ApiEndpoint(
            path="/api/atlas/v2/groups/{groupId}/clusters/{name}",
            method="GET",
            operation_id="getCluster",
            version="2024-08-05",
        ),
        "createCluster": ApiEndpoint(
            path="/api/atlas/v2/groups/{groupId}/clusters",
            method="POST",
            operation_id="createCluster",
            version="2024-08-05",
        ),
        "listGroups": ApiEndpoint(
            path="/api/atlas/v2/groups",
            method="GET",
            operation_id="listGroups",
            version="2023-01-01",
        ),
    }
    handwritten_usage = ResourceSdkUsage(
        resource_type="mongodbatlas_test_handwritten",
        package_path="internal/service/test",
        source=SourceKind.handwritten,
        sdk_calls=[
            SdkCall(api_group="ClustersApi", method_name="CreateCluster"),
            SdkCall(api_group="ClustersApi", method_name="GetClusterWithParams"),
            SdkCall(api_group="ProjectsApi", method_name="ListProjects"),
            SdkCall(api_group="ServerlessInstancesApi", method_name="CreateServerlessInstance"),
            SdkCall(api_group="OldApi", method_name="OldMethod", legacy=True),
        ],
    )
    results = resolve_endpoints([handwritten_usage], operation_index)
    assert len(results) == 1
    resolved_ops = {ep.operation_id for ep in results[0].endpoints}
    assert resolved_ops == {"createCluster", "getCluster", "listGroups"}
    versions = {ep.operation_id: ep.version for ep in results[0].endpoints}
    assert versions["getCluster"] == "2024-08-05"
    assert versions["listGroups"] == "2023-01-01"


def test_resolve_codegen_endpoints_version():
    operation_index = {
        "getThing": ApiEndpoint(
            path="/api/atlas/v2/groups/{groupId}/things/{name}",
            method="GET",
            operation_id="getThing",
            version="2024-08-05",
        ),
    }
    codegen_usage = ResourceSdkUsage(
        resource_type="mongodbatlas_thing",
        package_path="internal/serviceapi/thing",
        source=SourceKind.codegen,
        codegen_endpoints=[
            CodegenEndpoint(
                path="/api/atlas/v2/groups/{groupId}/things/{name}",
                method="GET",
                operation="read",
                version="2023-01-01",
            ),
            CodegenEndpoint(
                path="/api/atlas/v2/groups/{groupId}/things",
                method="POST",
                operation="create",
                version="2023-01-01",
            ),
        ],
    )
    results = resolve_endpoints([codegen_usage], operation_index)
    assert len(results) == 1
    versions = {ep.operation_id: ep.version for ep in results[0].endpoints}
    assert versions["getThing"] == "2024-08-05"
    assert versions["unknown_create"] == "2023-01-01"


def test_full_report(provider_repo_path, sdk_repo_path, tmp_path):
    output = tmp_path / "report.json"
    report = generate_sdk_usage_report(provider_repo_path, sdk_repo_path, output)
    assert output.exists()
    assert len(report.resources) > 50
    types = {r.resource_type for r in report.resources}
    assert any("cluster" in t for t in types)
    assert any("project" in t for t in types)
