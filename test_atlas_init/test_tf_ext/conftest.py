import os
from pathlib import Path
from model_lib import parse_dict
import pytest


@pytest.fixture()
@pytest.mark.skipif(os.environ.get("TF_VARIABLES_PATH", "") == "", reason="needs os.environ[TF_VARIABLES_PATH]")
def tf_variables_path():
    return Path(os.environ["TF_VARIABLES_PATH"])


@pytest.fixture()
@pytest.mark.skipif(
    os.environ.get("TF_PUSH_BASED_LOG_EXAMPLE", "") == "", reason="needs os.environ[TF_PUSH_BASED_LOG_EXAMPLE]"
)
def tf_push_based_log_example():
    return Path(os.environ["TF_PUSH_BASED_LOG_EXAMPLE"])


@pytest.fixture()
@pytest.mark.skipif(
    os.environ.get("TF_SEARCH_DEPLOYMENT_EXAMPLE", "") == "", reason="needs os.environ[TF_SEARCH_DEPLOYMENT_EXAMPLE]"
)
def tf_search_deployment_example_path():
    return Path(os.environ["TF_SEARCH_DEPLOYMENT_EXAMPLE"])


@pytest.fixture()
def atlas_schemas_dict() -> dict:
    return parse_dict(Path(__file__).parent / "testdata/atlas_schema.json")
