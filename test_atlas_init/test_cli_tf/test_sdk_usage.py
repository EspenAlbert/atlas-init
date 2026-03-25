import os
from pathlib import Path

import pytest

from atlas_init.cli_tf.sdk_usage import (
    ApiEndpoint,
    CodegenEndpoint,
    ResourceSdkUsage,
    SdkCall,
    SourceKind,
    build_operation_index,
    generate_sdk_usage_report,
    parse_codegen_config,
    resolve_endpoints,
    scan_handwritten_sdk_calls,
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


def test_build_operation_index(openapi_schema):
    index = build_operation_index(openapi_schema)
    assert len(index) > 0
    for op_id, ep in index.items():
        assert ep.operation_id == op_id
        assert ep.method
        assert ep.path


def test_resolve_endpoints():
    operation_index = {
        "getCluster": ApiEndpoint(
            path="/api/atlas/v2/groups/{groupId}/clusters/{name}", method="GET", operation_id="getCluster"
        ),
        "createCluster": ApiEndpoint(
            path="/api/atlas/v2/groups/{groupId}/clusters", method="POST", operation_id="createCluster"
        ),
    }
    codegen_usage = ResourceSdkUsage(
        resource_type="mongodbatlas_test_codegen",
        package_path="internal/serviceapi/test",
        source=SourceKind.codegen,
        codegen_endpoints=[
            CodegenEndpoint(path="/api/atlas/v2/groups/{groupId}/clusters/{name}", method="GET", operation="read"),
        ],
    )
    handwritten_usage = ResourceSdkUsage(
        resource_type="mongodbatlas_test_handwritten",
        package_path="internal/service/test",
        source=SourceKind.handwritten,
        sdk_calls=[
            SdkCall(api_group="ClustersApi", method_name="CreateCluster"),
            SdkCall(api_group="OldApi", method_name="OldMethod", legacy=True),
        ],
    )
    results = resolve_endpoints([codegen_usage, handwritten_usage], operation_index)
    assert len(results) == 2
    codegen_result = results[0]
    assert len(codegen_result.endpoints) == 1
    assert codegen_result.endpoints[0].operation_id == "getCluster"
    handwritten_result = results[1]
    assert len(handwritten_result.endpoints) == 1
    assert handwritten_result.endpoints[0].operation_id == "createCluster"


def test_full_report(provider_repo_path, live_api_spec, tmp_path):
    spec_path = provider_repo_path / "tools/codegen/atlasapispec/multi-version-api-spec.flattened.yml"
    if not spec_path.exists():
        pytest.skip("flattened spec not found in provider repo")
    output = tmp_path / "report.json"
    report = generate_sdk_usage_report(provider_repo_path, spec_path, output)
    assert output.exists()
    assert len(report.resources) > 50
    types = {r.resource_type for r in report.resources}
    assert any("cluster" in t for t in types)
    assert any("project" in t for t in types)
