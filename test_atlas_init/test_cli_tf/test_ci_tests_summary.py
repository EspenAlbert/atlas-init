from pathlib import Path
import pytest

from atlas_init.cli_tf.ci_tests_summary import find_env_of_mongodb_base_url, parse_tests
from atlas_init.cli_tf.go_test_run import GoTestStatus

_logs_TestAccCluster_create_RedactClientLogData = """\
2025-04-09T00:25:01.8116397Z === RUN   TestAccCluster_create_RedactClientLogData
2025-04-09T00:25:05.2244878Z     resource_cluster_test.go:1369: Step 1/1 error: Error running apply: exit status 1
2025-04-09T00:25:05.2245585Z         
2025-04-09T00:25:05.2246122Z         Error: error during project deletion when getting project settings
2025-04-09T00:25:05.2246941Z         
2025-04-09T00:25:05.2247261Z           with mongodbatlas_project.test,
2025-04-09T00:25:05.2247996Z           on terraform_plugin_test.tf line 12, in resource "mongodbatlas_project" "test":
2025-04-09T00:25:05.2248557Z           12: \t\tresource "mongodbatlas_project" "test" {
2025-04-09T00:25:05.2248852Z         
2025-04-09T00:25:05.2249207Z         error deleting project (67f5be5fe7455b55f206ba40):
2025-04-09T00:25:05.2249870Z         https://cloud-dev.mongodb.com/api/atlas/v2/groups/67f5be5fe7455b55f206ba40/settings
2025-04-09T00:25:05.2250562Z         GET: HTTP 404 Not Found (Error code: "RESOURCE_NOT_FOUND") Detail: Cannot
2025-04-09T00:25:05.2251214Z         find resource /api/atlas/v2/groups/67f5be5fe7455b55f206ba40/settings. Reason:
2025-04-09T00:25:05.2251888Z         Not Found. Params: [/api/atlas/v2/groups/67f5be5fe7455b55f206ba40/settings],
2025-04-09T00:25:05.2252329Z         BadRequestDetail: 
2025-04-09T00:25:05.2744864Z --- FAIL: TestAccCluster_create_RedactClientLogData (3.46s)"""

_logs_TestAccCluster_tenant = """\
2025-04-09T00:25:01.8107100Z === RUN   TestAccCluster_tenant
2025-04-09T00:59:12.0131855Z     resource_cluster_test.go:1029: Step 2/2 error: Check failed: Check 4/5 error: mongodbatlas_cluster.tenant: Attribute \'disk_size_gb\' expected "10", got "5"
2025-04-09T01:00:42.6195226Z --- FAIL: TestAccCluster_tenant (2140.81s)"""
logs_TestAccCluster_pinnedFCVWithVersionUpgradeAndDowngrade = """\
2025-04-09T00:25:01.8117740Z === RUN   TestAccCluster_pinnedFCVWithVersionUpgradeAndDowngrade
2025-04-09T00:25:05.8150912Z     resource_cluster_test.go:1399: Step 1/7 error: Error running apply: exit status 1
2025-04-09T00:25:05.8151338Z         
2025-04-09T00:25:05.8151883Z         Error: error during project deletion when getting project settings
2025-04-09T00:25:05.8152250Z         
2025-04-09T00:25:05.8152658Z           with mongodbatlas_project.test,
2025-04-09T00:25:05.8153361Z           on terraform_plugin_test.tf line 12, in resource "mongodbatlas_project" "test":
2025-04-09T00:25:05.8154373Z           12: \t\tresource "mongodbatlas_project" "test" {
2025-04-09T00:25:05.8154679Z         
2025-04-09T00:25:05.8155033Z         error deleting project (67f5be5fe7455b55f206ba3e):
2025-04-09T00:25:05.8155686Z         https://cloud-dev.mongodb.com/api/atlas/v2/groups/67f5be5fe7455b55f206ba3e/settings
2025-04-09T00:25:05.8156649Z         GET: HTTP 404 Not Found (Error code: "RESOURCE_NOT_FOUND") Detail: Cannot
2025-04-09T00:25:05.8157317Z         find resource /api/atlas/v2/groups/67f5be5fe7455b55f206ba3e/settings. Reason:
2025-04-09T00:25:05.8157985Z         Not Found. Params: [/api/atlas/v2/groups/67f5be5fe7455b55f206ba3e/settings],
2025-04-09T00:25:05.8158436Z         BadRequestDetail: 
2025-04-09T00:25:05.8592892Z --- FAIL: TestAccCluster_pinnedFCVWithVersionUpgradeAndDowngrade (4.05s)"""
_CLUSTER_LOGS_FILENAME = (
    "40216336752_tests-1.11.x-latest_tests-1.11.x-latest-false_cluster"
)
_ci_logs_test_data = [
    (
        _CLUSTER_LOGS_FILENAME,
        {
            "TestAccCluster_tenant": GoTestStatus.FAIL,
            "TestAccCluster_ProviderRegionName": GoTestStatus.PASS,
            "TestAccCluster_withPrivateEndpointLink": GoTestStatus.SKIP,
            "TestAccCluster_create_RedactClientLogData": GoTestStatus.FAIL,
            "TestAccCluster_pinnedFCVWithVersionUpgradeAndDowngrade": GoTestStatus.FAIL,
        },
        {
            "TestAccCluster_create_RedactClientLogData": _logs_TestAccCluster_create_RedactClientLogData,
            "TestAccCluster_tenant": _logs_TestAccCluster_tenant,
            "TestAccCluster_pinnedFCVWithVersionUpgradeAndDowngrade": logs_TestAccCluster_pinnedFCVWithVersionUpgradeAndDowngrade,
        },
    ),
]


@pytest.mark.parametrize(
    "log_file,test_results,test_output",
    _ci_logs_test_data,
    ids=[t[0] for t in _ci_logs_test_data],
)
def test_parsing_nested_test(
    github_ci_logs_dir: Path,
    log_file,
    test_results,
    test_output,
):
    file_path = github_ci_logs_dir / f"{log_file}.txt"
    found_tests = parse_tests(file_path.read_text().splitlines())
    assert found_tests
    found_tests_by_name = {test.name: test for test in found_tests}
    non_matching_statuses = [
        f"{test_name}: {found_tests_by_name[test_name].status} != {expected_status}"
        for test_name, expected_status in test_results.items()
        if found_tests_by_name[test_name].status != expected_status
    ]
    assert (
        not non_matching_statuses
    ), f"Test statuses do not match: {non_matching_statuses}"
    # sourcery skip: no-loop-in-tests
    for test_name, expected_output in test_output.items():
        assert (
            found_tests_by_name[test_name].output_lines_str == expected_output
        ), f"Test output does not match for {test_name}"


def test_find_env_of_mongodb_base_url(github_ci_logs_dir):
    logs_path = github_ci_logs_dir / f"{_CLUSTER_LOGS_FILENAME}.txt"
    assert find_env_of_mongodb_base_url(logs_path.read_text()) == "dev"
