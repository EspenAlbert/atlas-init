import pytest

from atlas_init.cli_cfn.contract import RunContractTest, contract_test
from atlas_init.repos.path import Repo
from test_atlas_init.conftest import CLIArgs


@pytest.mark.parametrize("resource_name", ["trigger"])
def test_contract_test(resource_name, cli_configure, cli_assertions):
    commands = [
        "go build",
        "sam local start-lambda",
        "cfn test",
    ]
    files = [
        "inputs/*.json",
        "samples/*.json",
    ]
    args = CLIArgs(
        repo=Repo.CFN,
        cfn_resource_name=resource_name,
        aws_profile="test",
        commands_expected=commands,
        files_glob_expected=files,
    )
    cli_configure(args)
    contract_test()
    cli_assertions(args)


def test_name_filter(tmp_path):
    assert RunContractTest(
        resource_path=tmp_path,
        repo_path=tmp_path,
        aws_profile="test",
        cfn_region="us-west-2",
        only_names=["contract_create_create", "contract_update_without_create"]
    ).run_tests_command[1] == "test --function-name TestEntrypoint --verbose --region us-west-2 -- -k contract_create_create -k contract_update_without_create"
