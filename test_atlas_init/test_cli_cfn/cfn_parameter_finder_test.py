import os
from pathlib import Path

import pytest
from model_lib import parse_payload

from atlas_init.cli_cfn.cfn_parameter_finder import (
    check_execution_role,
    decode_parameters,
    dump_resource_to_file,
    updated_template_path,
)

TEST_DATA = Path(__file__).parent / "test_data"


def test_decode_parameters_project():
    template_path, params, missing_params = decode_parameters(  # type: ignore
        {},
        TEST_DATA / "cfn_project_template.json",
        "MongoDB::Atlas::Project",
        "test-stack",
        {"TeamRoles": "FORCED"},  # type: ignore
    )
    print(params)
    assert missing_params
    team_roles_value = next(
        (p["ParameterValue"] for p in params if p["ParameterKey"] == "TeamRoles"), ""  # type: ignore
    )
    assert team_roles_value == "FORCED"
    assert sorted(missing_params) == ["KeyId", "OrgId", "TeamId"]  # type: ignore


@pytest.mark.skipif(
    os.environ.get("CFN_REPO_PATH", "") == "", reason="needs os.environ[CFN_REPO_PATH]"
)
def test_check_execution_role():
    cfn_repo_path = Path(os.environ["CFN_REPO_PATH"])
    some_arn = "arn:aws:iam::XXXX:role/cfn-execution-role"
    assert (
        check_execution_role(cfn_repo_path, {"CFN_EXAMPLE_EXECUTION_ROLE": some_arn})
        == some_arn
    )


def test_updated_template_path():
    assert (
        str(updated_template_path(Path("free-tier-M0-cluster.json")))
        == "free-tier-M0-cluster-updated.json"
    )


@pytest.mark.skipif(
    any(os.environ.get(name, "") == "" for name in ["SRC_TEMPLATE", "DEST_TEMPLATE"]),
    reason='needs env vars: ["SRC_TEMPLATE", "DEST_TEMPLATE"])',
)
def test_updates():
    src = Path(os.environ["SRC_TEMPLATE"])
    dest = Path(os.environ["DEST_TEMPLATE"])
    assert src.exists()
    assert dest.exists()
    assert parse_payload(src) == parse_payload(dest)


def test_dump_resource_to_file(tmp_path):
    params = [
        {"ParameterKey": "ProjectId", "ParameterValue": "664619d870c247237f4b86a6"},
        {"ParameterKey": "ClusterName", "ParameterValue": "cluster-example-test-espen"},
        {"ParameterKey": "Profile", "ParameterValue": "espen2"},
        {"ParameterKey": "PitEnabled", "ParameterValue": "false"},
    ]
    inputs_file = dump_resource_to_file(
        tmp_path,
        TEST_DATA / "cluster-self-managed-sharding.json",
        "MongoDB::Atlas::Cluster",
        params,  # type: ignore
    )
    assert '"Ref": ' not in inputs_file.read_text()
