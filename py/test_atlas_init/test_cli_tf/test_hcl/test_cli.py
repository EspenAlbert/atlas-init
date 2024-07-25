import os
from pathlib import Path
import pytest
from atlas_init.cli_tf.hcl.cli import convert_and_validate, read_cluster_import_ids


def test_read_cluster_import_ids(tf_test_data_dir):
    state_example = tf_test_data_dir / "cluster_mig/state_example.json"
    state = state_example.read_text()
    import_ids = read_cluster_import_ids(state)
    assert import_ids == {
        "664619d870c247237f4b86a6-legacy-cluster": "mongodbatlas_cluster.this"
    }


@pytest.mark.skipif(
    os.environ.get("TF_DIR", "") == "", reason="needs os.environ[TF_DIR]"
)
def test_convert_and_validate():
    tf_dir = Path(os.environ["TF_DIR"])
    convert_and_validate(tf_dir, is_interactive=False)
