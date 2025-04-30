import os
from pathlib import Path

import pytest
from model_lib import parse_payload

from atlas_init.cli_cfn.cfn_parameter_finder import (
    CfnTemplateUnknownParametersError,
    dump_resource_to_file,
    infer_template_parameters,
)

TEST_DATA = Path(__file__).parent / "test_data"


def test_infer_template_parameters(tmp_path):
    original_template = TEST_DATA / "cfn_project_template.json"
    template_path = tmp_path / "cfn_project_template.json"
    template_path.write_text(original_template.read_text())
    with pytest.raises(CfnTemplateUnknownParametersError) as exc:
        infer_template_parameters(
            template_path,
            "MongoDB::Atlas::Project",
            "test-stack",
            {"TeamRoles": "FORCED"},
        )
    assert exc.value.unknown_params == ["KeyId", "OrgId", "TeamId"]


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
