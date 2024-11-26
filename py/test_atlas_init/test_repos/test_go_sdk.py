from atlas_init.repos.go_sdk import download_admin_api


def test_download_admin_api(api_spec_path_transformed):
    assert api_spec_path_transformed.exists()
