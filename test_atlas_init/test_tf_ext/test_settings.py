from zero_3rdparty.file_utils import ensure_parents_write_text
from atlas_init.tf_ext.settings import parse_atlas_path_from_tf_cli_config_file, tf_cli_config_file_content


def test_parse_atlas_path_from_tf_cli_config_file(tmp_path):
    tf_cli_config_file = tmp_path / "tf_cli_config_file"
    repo_path = tmp_path / "atlas_provider"
    content = tf_cli_config_file_content(repo_path)
    ensure_parents_write_text(tf_cli_config_file, content)
    assert parse_atlas_path_from_tf_cli_config_file(tf_cli_config_file) == repo_path
