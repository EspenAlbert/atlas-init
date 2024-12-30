from atlas_init.cli_cfn.contract import contract_test
from atlas_init.repos.path import Repo
import pytest
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
