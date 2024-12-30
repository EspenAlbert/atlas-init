import logging
import os
from pathlib import Path
from typing import Callable

import pytest
from model_lib import parse_payload

from atlas_init.cli_tf.mock_tf_log import MockTFLog, mock_tf_log
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


params = [
    ("TestAccResourcePolicy_basic.log", "resourcepolicy"),
    ("TestAccClusterAdvancedCluster_basicTenant.log", "advancedcluster"),
    ("TestAccAdvancedCluster_configSharded.log", "advancedcluster"),
    ("TestAccAdvancedCluster_basic.log", "advancedcluster"),
]


@pytest.mark.skipif(os.environ.get("RUN_DEPRECATED", "") == "", reason="needs os.environ[RUN_DEPRECATED]")
@pytest.mark.parametrize(
    "log_filename,pkg_name",
    params,
    ids=[p[0] for p in params],
)
def test_mock_tf_log(
    api_spec_path_transformed,
    log_filename,
    pkg_name,
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
        keep_duplicates=False,
        package_name=pkg_name
    )
    output_path = mock_tf_log(req)
    parsed_again = parse_payload(output_path)
    assert parsed_again
    file_regression.check(output_path.read_text(), extension=".yaml")
