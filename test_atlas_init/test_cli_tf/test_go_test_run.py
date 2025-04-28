import logging
import os
from pathlib import Path

import pytest

from atlas_init.cli_tf.ci_tests import find_env_of_mongodb_base_url
from atlas_init.cli_tf.go_test_run import (
    GoTestRun,
    GoTestStatus,
    extract_group_name,
    parse_tests,
)

from atlas_init.cli_tf.go_test_run import GoTestStatus, parse_tests
from atlas_init.cli_tf.go_test_tf_error import (
    CheckError,
    DetailsInfo,
    GoTestAPIError,
    GoTestCheckError,
    parse_error_details,
)
from zero_3rdparty.datetime_utils import utc_now

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
_logs_TestAccCluster_pinnedFCVWithVersionUpgradeAndDowngrade = """\
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
_logs_TestAccBackupRSOnlineArchive = """\
2024-06-26T00:58:20.7853337Z === RUN   TestAccBackupRSOnlineArchive
2024-06-26T00:58:20.7918346Z     resource_online_archive_test.go:32: Step 2/7 error: Error running apply: exit status 1
2024-06-26T00:58:20.7919682Z         
2024-06-26T00:58:20.7920573Z         Error: error creating MongoDB Atlas Online Archive:: undefined response type
2024-06-26T00:58:20.7921224Z         
2024-06-26T00:58:20.7921829Z           with mongodbatlas_online_archive.users_archive,
2024-06-26T00:58:20.7923085Z           on terraform_plugin_test.tf line 52, in resource "mongodbatlas_online_archive" "users_archive":
2024-06-26T00:58:20.7924127Z           52: \tresource "mongodbatlas_online_archive" "users_archive" {
2024-06-26T00:58:20.7924792Z         
2024-06-26T00:58:20.7946475Z --- FAIL: TestAccBackupRSOnlineArchive (1149.23s)"""
_logs_TestAccBackupRSOnlineArchiveWithProcessRegion = """\
2024-06-26T00:58:20.7859743Z === RUN   TestAccBackupRSOnlineArchiveWithProcessRegion
2024-06-26T00:58:20.7939774Z     resource_online_archive_test.go:183: Step 2/4 error: Error running apply: exit status 1
2024-06-26T00:58:20.7940563Z         
2024-06-26T00:58:20.7941236Z         Error: error creating MongoDB Atlas Online Archive:: undefined response type
2024-06-26T00:58:20.7941974Z         
2024-06-26T00:58:20.7942499Z           with mongodbatlas_online_archive.users_archive,
2024-06-26T00:58:20.7943507Z           on terraform_plugin_test.tf line 52, in resource "mongodbatlas_online_archive" "users_archive":
2024-06-26T00:58:20.7944500Z           52: \tresource "mongodbatlas_online_archive" "users_archive" {
2024-06-26T00:58:20.7945036Z         
2024-06-26T00:58:20.7945708Z --- FAIL: TestAccBackupRSOnlineArchiveWithProcessRegion (1139.13s)"""
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
            "TestAccCluster_pinnedFCVWithVersionUpgradeAndDowngrade": _logs_TestAccCluster_pinnedFCVWithVersionUpgradeAndDowngrade,
        },
    ),
    (
        "30230451013_tests-1.9.x-latest_tests-1.9.x-latest-dev_config",
        {
            "TestAccConfigDSAtlasUsers_InvalidAttrCombinations/invalid_empty_attributes_defined": GoTestStatus.PASS,
            "TestAccProjectAPIKey_changingSingleProject": GoTestStatus.FAIL,
        },
        {},
    ),
    (
        "backup_logs_multiple_failures_with_context",
        {},
        {
            "TestAccBackupRSOnlineArchive": _logs_TestAccBackupRSOnlineArchive,
            "TestAccBackupRSOnlineArchiveWithProcessRegion": _logs_TestAccBackupRSOnlineArchiveWithProcessRegion,
        },
    ),
]


@pytest.mark.parametrize(
    "log_file,test_results,test_output",
    _ci_logs_test_data,
    ids=[t[0] for t in _ci_logs_test_data],
)
def test_parsing_ci_logs(
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


def check_status_counts(
    tests: list[GoTestRun],
    fail_count: int,
    skip_count: int,
    pass_count: int,
    run_count: int = 0,
):
    group_counts = {
        GoTestStatus.FAIL: fail_count,
        GoTestStatus.SKIP: skip_count,
        GoTestStatus.PASS: pass_count,
        GoTestStatus.RUN: run_count,
    }
    for status, count in group_counts.items():
        group_tests = [t for t in tests if t.status == status]
        assert (
            len(group_tests) == count
        ), f"wrong count for {status}, got {len(group_tests)} expected {count}"


_expected_pass_names = {
    "TestMigNetworkContainer_basicAWS",
    "TestMigNetworkContainer_basicAzure",
    "TestMigNetworkContainer_basicGCP",
    "TestAccNetworkContainer_withRegionsGCP",
    "TestAccNetworkContainer_updateIndividualFields",
    "TestAccNetworkContainer_basicAzure",
    "TestAccNetworkContainer_basicGCP",
    "TestAccNetworkContainer_basicAWS",
    "TestAccNetworkRSNetworkPeering_basicAzure",
    "TestAccNetworkNetworkPeering_basicAWS",
    "TestMigNetworkNetworkPeering_basicAWS",
    "TestAccNetworkRSNetworkPeering_AWSDifferentRegionName",
    "TestMigPrivateEndpointRegionalMode_basic",
    "TestAccPrivateEndpointRegionalMode_basic",
    "TestAccNetworkRSPrivateLinkEndpointAzure_basic",
    "TestAccNetworkRSPrivateLinkEndpointAWS_basic",
    "TestMigNetworkPrivateLinkEndpoint_basic",
    "TestAccNetworkRSPrivateLinkEndpointGCP_basic",
    "TestAccNetworkPrivatelinkEndpointServiceDataFederationOnlineArchiveDS_basic",
    "TestAccNetworkPrivatelinkEndpointServiceDataFederationOnlineArchivesDSPlural_basic",
    "TestMigNetworkPrivatelinkEndpointServiceDataFederationOnlineArchive_basic",
    "TestAccNetworkPrivatelinkEndpointServiceDataFederationOnlineArchive_basic",
    "TestAccNetworkPrivatelinkEndpointServiceDataFederationOnlineArchive_updateComment",
    "TestAccNetworkPrivatelinkEndpointServiceDataFederationOnlineArchive_basicWithRegionDnsName",
}

_network_logs_one_failure = (
    Path(__file__).parent / "test_data/network_logs_one_failure.txt"
)


def test_parse():
    tests = parse_tests(_network_logs_one_failure.read_text().splitlines())
    missing_passing = _expected_pass_names - {
        t.name for t in tests if t.status == GoTestStatus.PASS
    }
    assert not missing_passing, f"missing passing tests: {missing_passing}"
    assert tests
    check_status_counts(tests, fail_count=1, skip_count=6, pass_count=24)


@pytest.mark.skipif(
    os.environ.get("TESTDIR_MAKE_MOCKABLE", "") == "",
    reason="needs os.environ[TESTDIR_MAKE_MOCKABLE]",
)
def test_rename_directories_and_files():
    path = Path(os.environ["TESTDIR_MAKE_MOCKABLE"])
    paths = path.glob("*")
    for p in paths:
        if not p.name.startswith("TestAccMockable"):
            p.rename(p.with_name(p.name.replace("TestAcc", "TestAccMockable")))


def test_extract_group_name():
    assert (
        extract_group_name(
            Path(
                "40216340925_tests-1.11.x-latest_tests-1.11.x-latest-false_search_deployment.txt"
            )
        )
        == "search_deployment"
    )


api_error_project_not_found = GoTestAPIError(
    api_error_code_str="RESOURCE_NOT_FOUND",
    api_method="GET",
    api_response_code=404,
    tf_resource_name="test",
    tf_resource_type="project",
    step_nr=1,
    api_path="/api/atlas/v2/groups/67f5be5fe7455b55f206ba3e/settings",
)


@pytest.mark.parametrize(
    "logs_str,expected_details",
    [
        (
            _logs_TestAccCluster_tenant,
            GoTestCheckError(
                tf_resource_name="tenant",
                tf_resource_type="cluster",
                step_nr=2,
                check_errors=[CheckError(check_nr=4)],
            ),
        ),
        (
            _logs_TestAccCluster_pinnedFCVWithVersionUpgradeAndDowngrade,
            api_error_project_not_found,
        ),
    ],
    ids=["tenant should create GoTestCheckError", "api error should be parsed"],
)
def test_extract_error_details(logs_str, expected_details):
    run = dummy_run(logs_str, "extract-error-details")
    assert expected_details == parse_error_details(run)


def dummy_run(logs_str: str, name: str):
    return GoTestRun(name=name, output_lines=logs_str.splitlines(), ts=utc_now())
