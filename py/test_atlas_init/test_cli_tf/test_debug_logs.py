from io import StringIO
import json
import logging
from os import getenv
from typing import Callable
from atlas_init.cli_tf.debug_logs import SDKRoundtrip, parse_http_requests, parsed
from atlas_init.cli_tf.debug_logs_test_data import (
    create_mock_data,
    default_is_diff,
)
from atlas_init.cli_tf.debug_logs_test_data import RTModifier
from atlas_init.repos.go_sdk import parse_api_spec_paths
from model_lib import dump, parse_payload
import pytest
import yaml

logger = logging.getLogger(__name__)


@pytest.fixture
def log_file_text(tf_test_data_dir) -> Callable[[str], str]:
    def read_log_file_text(file_name: str) -> str:
        path = tf_test_data_dir / "tf_acc_logs" / file_name
        return path.read_text()

    return read_log_file_text


def log_roundtrips(
    roundtrips: list[SDKRoundtrip], differ: Callable[[SDKRoundtrip], bool] | None = None
):
    differ = differ or default_is_diff
    diff_count = 0
    step_nr = 0
    for rt in roundtrips:
        if not differ(rt):
            continue
        if rt.step_number != step_nr:
            logger.info(f"{'-' * 80}\nStep {rt.step_number}")
            step_nr = rt.step_number
        diff_count += 1
        logger.info(
            f"\n{rt.request.method} {rt.request.path}\n{rt.request.text}\n{rt.response.status}-{rt.response.status_text}\n{rt.response.text}"
        )
    logger.info(f"Diffable requests: {diff_count}")


@pytest.fixture(scope="session")
def api_spec_paths(sdk_repo_path):
    return parse_api_spec_paths(sdk_repo_path)


_resource_policy_log = "TestAccResourcePolicy_basic.log"
_unit_tested_logs = {_resource_policy_log}

_diff_overrides = {
    _resource_policy_log: lambda rt: rt.request.method in {"POST", "PUT", "PATCH"}
    and not rt.request.path.endswith(":validate")
}


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
    ("TestAccResourcePolicy_basic.log", []),
    ("TestAccClusterAdvancedCluster_basicTenant.log", []),
    ("TestAccAdvancedCluster_configSharded.log", [cluster_modifier]),
    ("TestAccAdvancedCluster_basic.log", [cluster_modifier]),
]


@pytest.mark.parametrize(
    "log_filename,modifiers",
    params,
    ids=[p[0] for p in params],
)
def test_parse_http_requests(
    log_filename, modifiers, log_file_text, api_spec_paths, file_regression
):
    assert len(api_spec_paths) == 5
    roundtrips = parse_http_requests(log_file_text(log_filename))
    # sourcery skip: no-conditionals-in-tests
    if log_filename in _unit_tested_logs:
        assert len(roundtrips) == 35
    differ = _diff_overrides.get(log_filename)
    if getenv("LOG_ROUNDTRIPS"):
        log_roundtrips(roundtrips, differ)
    data = create_mock_data(
        roundtrips,
        api_spec_paths,
        is_diff=differ,
        modifiers=modifiers,
    )
    # avoid anchors
    data_parsed = json.loads(dump(data, "json"))
    s = StringIO()
    yaml.safe_dump(
        data_parsed,
        s,
        default_flow_style=False,
        width=100_000,
        allow_unicode=True,
        sort_keys=False,
    )
    data_yaml = s.getvalue()
    parsed_again = parse_payload(data_yaml, "yaml")
    assert parsed_again
    file_regression.check(data_yaml, extension=".yaml")
