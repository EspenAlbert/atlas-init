from atlas_init.repos.go_sdk import download_admin_api


def test_download_admin_api(tmp_path):
    dest_path = tmp_path / "atlas-api-transformed.yaml"
    download_admin_api(dest_path)
    assert dest_path.exists()
