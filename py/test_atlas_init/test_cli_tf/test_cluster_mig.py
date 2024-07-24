import logging
import os
from pathlib import Path
import pytest

from atlas_init.cli_tf.hcl.cluster_mig import (
    convert_cluster_config,
    convert_clusters,
    parse_and_convert_cluster_blocks,
)

logger = logging.getLogger(__name__)


def read_examples() -> list[tuple[str, str, str]]:
    TEST_DATA = Path(__file__).parent / "test_data/cluster_mig"

    def as_test_case(path: Path) -> tuple[str, str, str]:
        filename = path.name.replace("_expected", "")
        return filename, (path.parent / filename).read_text(), path.read_text()

    return sorted([as_test_case(path) for path in TEST_DATA.glob("*_expected.tf")])


examples = read_examples()
ERROR_PREFIX = "# error: "


@pytest.mark.parametrize(
    "name,legacy,expected", examples, ids=[name for name, *_ in examples]
)
def test_convert_cluster(name, legacy, expected):
    if expected.startswith(ERROR_PREFIX):
        with pytest.raises(ValueError) as exc:
            convert_cluster_config(legacy)
        assert str(exc.value) == expected.removeprefix(ERROR_PREFIX)
        return
    new_config = convert_cluster_config(legacy)
    print(f"new config for name: {name}f")
    print(new_config)
    assert new_config == expected


@pytest.mark.skipif(
    os.environ.get("TF_DIR", "") == "", reason="needs os.environ[TF_DIR]"
)
def test_live_no_plan_changes():
    tf_dir = Path(os.environ["TF_DIR"])
    assert convert_clusters(tf_dir)
