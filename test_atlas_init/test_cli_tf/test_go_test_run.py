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

from atlas_init.cli_tf.go_test_tf_error import (
    CheckError,
    GoTestAPIError,
    GoTestCheckError,
    parse_error_details,
)
from zero_3rdparty.datetime_utils import utc_now

logger = logging.getLogger(__name__)
_CLUSTER_LOGS_FILENAME = "40216336752_tests-1.11.x-latest_tests-1.11.x-latest-false_cluster"

_ci_logs_test_data = [
    (
        _CLUSTER_LOGS_FILENAME,
        {
            "cluster/TestAccCluster_tenant": GoTestStatus.FAIL,
            "cluster/TestAccCluster_ProviderRegionName": GoTestStatus.PASS,
            "cluster/TestAccCluster_withPrivateEndpointLink": GoTestStatus.SKIP,
            "cluster/TestAccCluster_create_RedactClientLogData": GoTestStatus.FAIL,
            "cluster/TestAccCluster_pinnedFCVWithVersionUpgradeAndDowngrade": GoTestStatus.FAIL,
        },
        [
            "cluster/TestAccCluster_create_RedactClientLogData",
            "cluster/TestAccCluster_tenant",
            "cluster/TestAccCluster_pinnedFCVWithVersionUpgradeAndDowngrade",
        ],
    ),
    (
        "30230451013_tests-1.9.x-latest_tests-1.9.x-latest-dev_config",
        {
            "atlasuser/TestAccConfigDSAtlasUsers_InvalidAttrCombinations/invalid_empty_attributes_defined": GoTestStatus.PASS,
            "projectapikey/TestAccProjectAPIKey_changingSingleProject": GoTestStatus.FAIL,
        },
        [],
    ),
    (
        "backup_logs_multiple_failures_with_context",
        {},
        [
            "onlinearchive/TestAccBackupRSOnlineArchive",
            "onlinearchive/TestAccBackupRSOnlineArchiveWithProcessRegion",
        ],
    ),
    (
        "41215865444_tests-1.11.x-latest_tests-1.11.x-latest-qa_stream",
        {},
        [
            "streamprocessor/TestAccStreamProcessor_StateTransitionsUpdates/StoppedToStarted",
            "streamprocessor/TestAccStreamProcessor_InvalidStateTransitionUpdates/StoppedToCreated",
        ],
    ),
    (
        "41241715011_tests-1.11.x-latest_tests-1.11.x-latest-false_cluster",
        {},
        ["cluster/TestAccCluster_basicGCPRegionNameWesternUS"],
    ),
    (
        "41313624603_tests-1.11.x-latest_tests-1.11.x-latest-false_stream",
        {},
        [
            "streamconnection/TestAccStreamRSStreamConnection_kafkaNetworkingVPC",
            "streamprocessor/TestAccStreamProcessor_InvalidStateTransitionUpdates/StartedToCreated",
        ],
    ),
    (
        "41241718467_tests-1.11.x-latest_tests-1.11.x-latest-false_stream",
        {},
        ["streamprocessor/TestAccStreamProcessor_InvalidStateTransitionUpdates/StoppedToCreated"],
    ),
    (
        "43584025455_1.12.x-latest-2.0.0_tests-1.12.x-latest-false_advanced_cluster_tpf",
        {"advancedcluster/TestAccClusterAdvancedCluster_replicaSetAWSProvider": GoTestStatus.TIMEOUT},
        [
            "advancedcluster/TestAccClusterAdvancedCluster_replicaSetAWSProvider",
        ],
    ),
]
TEST_LINES_SPLIT_SYMBOL = "\nNEXT_TEST\n"


def dump_test_output(run: GoTestRun) -> str:
    assert run.is_failure, f"test output only for failures, got {run.status} for {run.name}"
    return f"{run.name}\n{run.output_lines_str}"


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
    file_regression,
):
    file_path = github_ci_logs_dir / f"{log_file}.log"
    found_tests = parse_tests(file_path.read_text().splitlines())
    assert found_tests
    found_tests_by_name = {test.name_with_package: test for test in found_tests}
    names = "\n".join(sorted(found_tests_by_name))
    logger.info(f"found tests names: {names}")
    non_matching_statuses = [
        f"{test_name}: {found_tests_by_name[test_name].status} != {expected_status}"
        for test_name, expected_status in test_results.items()
        if found_tests_by_name[test_name].status != expected_status
    ]
    assert not non_matching_statuses, f"Test statuses do not match: {non_matching_statuses}"
    # sourcery skip: no-loop-in-tests
    # sourcery skip: no-conditionals-in-tests
    if not test_output:
        return
    test_output_logs = [dump_test_output(found_tests_by_name[test_name]) for test_name in test_output]
    all_log_lines = TEST_LINES_SPLIT_SYMBOL.join(test_output_logs)
    file_regression.check(all_log_lines, extension=".log")


def test_find_env_of_mongodb_base_url(github_ci_logs_dir):
    logs_path = github_ci_logs_dir / f"{_CLUSTER_LOGS_FILENAME}.log"
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
        assert len(group_tests) == count, f"wrong count for {status}, got {len(group_tests)} expected {count}"


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

_network_logs_one_failure = Path(__file__).parent / "test_data/network_logs_one_failure.txt"


def test_parse():
    tests = parse_tests(_network_logs_one_failure.read_text().splitlines())
    missing_passing = _expected_pass_names - {t.name for t in tests if t.status == GoTestStatus.PASS}
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
        extract_group_name(Path("40216340925_tests-1.11.x-latest_tests-1.11.x-latest-false_search_deployment.txt"))
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

api_error_stream_processor_generic = GoTestAPIError(
    api_error_code_str="STREAM_PROCESSOR_GENERIC_ERROR",
    api_method="POST",
    api_response_code=400,
    tf_resource_name="processor",
    tf_resource_type="stream_processor",
    step_nr=1,
    api_path="/api/atlas/v2/groups/680d7a6ff71e7361cf7450a7/streams/test-acc-tf-8577699112048547047-STARTED-STOPPED-STARTED/processor",
)

api_error_out_of_capacity = GoTestAPIError(
    api_error_code_str="OUT_OF_CAPACITY",
    api_method="POST",
    api_response_code=409,
    tf_resource_name="test",
    tf_resource_type="cluster",
    step_nr=1,
    api_path="/api/atlas/v1.0/groups/680ecbc7122f5b15cc627ba5/clusters",
)

api_error_unexpected_error = GoTestAPIError(
    api_error_code_str="UNEXPECTED_ERROR",
    api_method="DELETE",
    api_response_code=500,
    tf_resource_name="",
    tf_resource_type="",
    step_nr=-1,
    api_path="/api/atlas/v2/groups/680ecbbe1ad7050ec5b1ebe3/backupCompliancePolicy",
)


def read_test_logs(test_name: str) -> str:
    test_file_path = Path(__file__)
    logs_dir = test_file_path.parent / test_file_path.stem
    test_logs = {}
    for log_file in logs_dir.glob(f"{test_parsing_ci_logs.__name__}*.log"):
        parts = log_file.read_text().split(TEST_LINES_SPLIT_SYMBOL)
        for part in parts:
            name, *log_lines = part.splitlines()
            test_logs[name] = "\n".join(log_lines)
    return test_logs[test_name]


@pytest.mark.parametrize(
    "test_name,expected_details",
    [
        (
            "TestAccCluster_tenant",
            GoTestCheckError(
                tf_resource_name="tenant",
                tf_resource_type="cluster",
                step_nr=2,
                check_errors=[CheckError(check_nr=4)],
            ),
        ),
        (
            "TestAccCluster_pinnedFCVWithVersionUpgradeAndDowngrade",
            api_error_project_not_found,
        ),
        (
            "TestAccStreamProcessor_StateTransitionsUpdates/StoppedToStarted",
            api_error_stream_processor_generic,
        ),
        (
            "TestAccCluster_basicGCPRegionNameWesternUS",
            api_error_out_of_capacity,
        ),
        (
            "TestAccBackupCompliancePolicy_UpdateSetsAllAttributes",
            api_error_unexpected_error,
        ),
    ],
    ids=[
        "tenant should create GoTestCheckError",
        "api error with params",
        "api error without params",
        "api error no details",
        "api error no TF resource or type",
    ],
)
def test_extract_error_details(test_name, expected_details):
    logs_str = read_test_logs(test_name)
    run = dummy_run(logs_str, "extract-error-details")
    assert expected_details == parse_error_details(run)


def dummy_run(logs_str: str, name: str):
    return GoTestRun(name=name, output_lines=logs_str.splitlines(), ts=utc_now())
