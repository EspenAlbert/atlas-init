import os
from pathlib import Path

from atlas_init.cli_tf.debug_logs_test_data import find_normalized_path
from atlas_init.repos.go_sdk import download_admin_api, parse_api_spec_paths


def test_download_admin_api(api_spec_path_transformed):
    assert api_spec_path_transformed.exists()


# @pytest.mark.skipif(os.environ.get("DOWNLOAD_ADMIN_API", "false").lower() not in ("true", "1", "yes"), reason="skip marked tests")
def test_download_admin_api_live(tmp_path: Path):
    dest = tmp_path / "admin_api.yaml"
    download_admin_api(dest, branch="master")
    paths = parse_api_spec_paths(dest)
    method = os.environ.get("API_METHOD", "POST")
    path = os.environ.get("API_PATH", "/api/atlas/v2/groups/695da931d59b8466ea725024/streams/test-acc-tf-s-2241396692592931656/processor/processor-created-to-started:start")
    path_spec = find_normalized_path(path, paths[method])
    assert path_spec
