import os
from pathlib import Path

from atlas_init.cfn_parameter_finder import check_execution_role, decode_parameters

TEST_DATA = Path(__file__).parent / "test_data"


def test_decode_parameters_project():
    params, missing_params = decode_parameters(
        {},
        TEST_DATA / "cfn_project_template.json",
        "test-stack",
        {"TeamRoles": "FORCED"},
    )
    print(params)
    assert missing_params
    team_roles_value = next(
        (p["ParameterValue"] for p in params if p["ParameterKey"] == "TeamRoles"), ""  # type: ignore
    )
    assert team_roles_value == "FORCED"
    assert sorted(missing_params) == ["KeyId", "OrgId", "TeamId"]


def test_check_execution_role():
    cfn_repo_path = Path(os.environ["CFN_REPO_PATH"])
    some_arn = "arn:aws:iam::XXXX:role/cfn-execution-role"
    assert (
        check_execution_role(cfn_repo_path, {"CFN_EXAMPLE_EXECUTION_ROLE": some_arn})
        == some_arn
    )
