import json
import logging
from pathlib import Path
from typing import Callable

from atlas_init.cli_tf.mock_tf_log import MockTFLog, mock_tf_log
import pytest
import yaml
from model_lib import parse_payload

from atlas_init.cli_tf.debug_logs import SDKRoundtrip, parsed
from atlas_init.cli_tf.debug_logs_test_data import (
    RTModifier,
)
from atlas_init.repos.go_sdk import parse_api_spec_paths

logger = logging.getLogger(__name__)


@pytest.fixture
def log_file_path(tf_test_data_dir) -> Callable[[str], Path]:
    def read_log_file_text(file_name: str) -> Path:
        return tf_test_data_dir / "tf_acc_logs" / file_name

    return read_log_file_text


@pytest.fixture(scope="session")
def api_spec_paths(api_spec_path_transformed: Path):
    return parse_api_spec_paths(api_spec_path_transformed)


_resource_policy_log = "TestAccResourcePolicy_basic.log"

_suffixes_skipped = {_resource_policy_log: [":validate"]}


def add_label_tags(rt: SDKRoundtrip):
    logger.info(f"Adding labels and tags to {rt.id}")
    request = rt.request
    req_dict, req_list = parsed(request.text)
    response = rt.response
    resp_dict, resp_list = parsed(response.text)
    if resp_list or req_list:
        return
    for extra_field in ["labels", "tags"]:
        if extra_field not in resp_dict:
            resp_dict[extra_field] = []
        if extra_field not in req_dict:
            req_dict[extra_field] = []
    request.text = json.dumps(req_dict, indent=1, sort_keys=True)
    response.text = json.dumps(resp_dict, indent=1, sort_keys=True)


cluster_modifier = RTModifier(
    version="2024-08-05",
    method="POST",
    path="/api/atlas/v2/groups/{groupId}/clusters",
    modification=add_label_tags,
)


params = [
    (_resource_policy_log, []),
    ("TestAccClusterAdvancedCluster_basicTenant.log", []),
    ("TestAccAdvancedCluster_configSharded.log", [cluster_modifier]),
    ("TestAccAdvancedCluster_basic.log", [cluster_modifier]),
]


@pytest.mark.parametrize(
    "log_filename,modifiers",
    params,
    ids=[p[0] for p in params],
)
def test_mock_tf_log(
    api_spec_path_transformed,
    log_filename,
    modifiers,
    log_file_path,
    file_regression,
    tmp_path,
):
    test_data = tmp_path / "testdata"
    test_data.mkdir()
    req = MockTFLog(
        log_path=log_file_path(log_filename),
        output_dir=test_data,
        admin_api_path=api_spec_path_transformed,
        diff_skip_suffixes=_suffixes_skipped.get(log_filename, []),
        keep_duplicates=False,
        modifiers=modifiers,
    )
    output_path = mock_tf_log(req)
    parsed_again = parse_payload(output_path)
    assert parsed_again
    file_regression.check(output_path.read_text(), extension=".yaml")
