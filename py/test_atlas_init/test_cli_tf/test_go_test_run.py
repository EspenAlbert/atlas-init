from pathlib import Path

import pytest

from atlas_init.cli_tf.go_test_run import (
    GoTestRun,
    GoTestStatus,
    context_start_match,
    extract_context,
    match_line,
    parse,
)

_network_logs_one_failure = (
    Path(__file__).parent / "test_data/network_logs_one_failure.txt"
)
_backup_logs_multiple_failures_with_context = (
    Path(__file__).parent / "test_data/backup_logs_multiple_failures_with_context.txt"
)


_ok_examples = """\
2024-06-26T04:41:47.7209465Z === RUN   TestAccNetworkDSPrivateLinkEndpoint_basic
2024-06-26T04:41:47.7228652Z --- PASS: TestAccNetworkRSPrivateLinkEndpointGCP_basic (424.50s)
2024-06-26T04:41:47.7168636Z --- FAIL: TestAccNetworkRSNetworkPeering_updateBasicAzure (443.97s)
=== RUN   TestAccResourcePolicy_invalidConfig
--- PASS: TestAccResourcePolicy_invalidConfig (4.67s)
2024-06-26T04:41:47.7171679Z --- SKIP: TestAccNetworkRSNetworkPeering_basicGCP (0.00s)"""

_none_examples = """\
2024-06-26T04:41:47.7229504Z PASS
2024-09-17T00:22:05.6676147Z === RUN   TestAccConfigDSAtlasUsers_InvalidAttrCombinations/invalid_team_attribute_defined
2024-06-26T04:41:47.7189990Z Project deletion failed: 667b98b5487d301c7124414d, error: https://cloud-dev.mongodb.com/api/atlas/v2/groups/667b98b5487d301c7124414d DELETE: HTTP 409 Conflict (Error code: "CANNOT_CLOSE_GROUP_ACTIVE_PEERING_CONNECTIONS") Detail: There are active peering connections in this project. Reason: Conflict. Params: []"""


@pytest.mark.parametrize("line", _ok_examples.splitlines(keepends=True))
def test_match_line(line):
    assert match_line(line) is not None


@pytest.mark.parametrize("line", _none_examples.splitlines())
def test_no_match_line(line):
    assert match_line(line) is None


def parse_tests(path: Path, job) -> list[GoTestRun]:
    log_lines = path.read_text().splitlines()
    return list(parse(log_lines, job, test_step_nr=5))


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
        assert len(group_tests) == count, f"wrong count for {status}"


def test_parse(mock_job):
    tests = parse_tests(_network_logs_one_failure, mock_job)
    assert tests
    check_status_counts(tests, fail_count=1, skip_count=6, pass_count=24)


_backup_context_1 = """\
resource_online_archive_test.go:32: Step 2/7 error: Error running apply: exit status 1
    
    Error: error creating MongoDB Atlas Online Archive:: undefined response type
    
      with mongodbatlas_online_archive.users_archive,
      on terraform_plugin_test.tf line 52, in resource "mongodbatlas_online_archive" "users_archive":
      52: 	resource "mongodbatlas_online_archive" "users_archive" {"""
_backup_context_1_name = "TestAccBackupRSOnlineArchive"
_backup_context_2 = """\
resource_online_archive_test.go:183: Step 2/4 error: Error running apply: exit status 1
    
    Error: error creating MongoDB Atlas Online Archive:: undefined response type
    
      with mongodbatlas_online_archive.users_archive,
      on terraform_plugin_test.tf line 52, in resource "mongodbatlas_online_archive" "users_archive":
      52: 	resource "mongodbatlas_online_archive" "users_archive" {"""
_backup_context_2_name = "TestAccBackupRSOnlineArchiveWithProcessRegion"


def check_test(
    tests: list[GoTestRun], name: str, context_lines: str, status: GoTestStatus, url: str = ""
):
    found_tests = [t for t in tests if t.name == name]
    assert found_tests, f"couldn't find test with name={name}"
    assert (
        len(found_tests) == 1
    ), f"found multiple tests with name={name}: {found_tests}"
    test = found_tests[0]
    assert test.status == status
    if url:
        assert url == test.url
    assert context_lines in test.context_lines_str
    print(f"{test.name} context lines:\n{test.context_lines_str}")


def test_parse_with_error_context(mock_job):
    tests = parse_tests(_backup_logs_multiple_failures_with_context, mock_job)
    assert tests
    check_status_counts(tests, fail_count=4, skip_count=0, pass_count=19)
    check_test(tests, _backup_context_1_name, _backup_context_1, GoTestStatus.FAIL, "https://github.com/mongodb/terraform-provider-mongodbatlas/actions/runs/9671377861/job/26681936440#step:5:235")
    check_test(tests, _backup_context_2_name, _backup_context_2, GoTestStatus.FAIL)


def test_context_start_match():
    assert context_start_match("2024-06-26T00:58:20.7916997Z === NAME  TestAccBackupRSOnlineArchive") == 'TestAccBackupRSOnlineArchive'

_context_lines = """\
2024-06-26T00:58:20.7918346Z     resource_online_archive_test.go:32: Step 2/7 error: Error running apply: exit status 1
2024-06-26T00:58:20.7919682Z         
2024-06-26T00:58:20.7920573Z         Error: error creating MongoDB Atlas Online Archive:: undefined response type
2024-06-26T00:58:20.7921224Z         
2024-06-26T00:58:20.7921829Z           with mongodbatlas_online_archive.users_archive,
2024-06-26T00:58:20.7923085Z           on terraform_plugin_test.tf line 52, in resource "mongodbatlas_online_archive" "users_archive":
2024-06-26T00:58:20.7924127Z           52: 	resource "mongodbatlas_online_archive" "users_archive" {"""

_expected_context_lines = """\
resource_online_archive_test.go:32: Step 2/7 error: Error running apply: exit status 1
    
    Error: error creating MongoDB Atlas Online Archive:: undefined response type
    
      with mongodbatlas_online_archive.users_archive,
      on terraform_plugin_test.tf line 52, in resource "mongodbatlas_online_archive" "users_archive":
      52: 	resource "mongodbatlas_online_archive" "users_archive" {"""


def test_context_lines():
    full_context = []
    for line in _context_lines.splitlines():
        if more_context := extract_context(line):
            full_context.append(more_context)
    assert _expected_context_lines == "\n".join(full_context)


def test_parsing_nested_test(github_ci_logs_dir: Path, mock_job):
    file_path = github_ci_logs_dir / "30230451013_tests-1.9.x-latest_tests-1.9.x-latest-dev_config.txt"
    tests = parse_tests(file_path, mock_job)
    nested_test = "TestAccConfigDSAtlasUsers_InvalidAttrCombinations"
    nested_test = next((test for test in tests if test.name == nested_test), None)
    assert nested_test
    assert nested_test.status == GoTestStatus.PASS
