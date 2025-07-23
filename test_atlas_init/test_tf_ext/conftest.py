import os
from pathlib import Path
from model_lib import parse_dict
import pytest
from zero_3rdparty.str_utils import ensure_suffix


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
    schema_path = Path(__file__).parent / "testdata/atlas_schema.json"
    if not schema_path.exists():
        pytest.skip("schema_path does not exist")
    return parse_dict(schema_path)


@pytest.fixture()
def resource_type_schema_path():
    def inner(resource_type: str) -> Path:
        return Path(__file__).parent / "testdata/resources" / f"{resource_type}.json"

    return inner


@pytest.fixture()
def generated_dataclass_path():
    def inner(resource_type: str) -> Path:
        return Path(__file__).parent / "testdata/dataclasses" / f"{resource_type}.py"

    return inner


@pytest.fixture()
def generated_main_path():
    def inner(resource_type: str) -> Path:
        return Path(__file__).parent / "testdata/main" / f"{resource_type}.tf"

    return inner


@pytest.fixture()
def generated_variables_path():
    def inner(resource_type: str) -> Path:
        return Path(__file__).parent / "testdata/variables" / f"{resource_type}.tf"

    return inner


@pytest.fixture()
def dataclass_manual_path():
    def inner(filename: str) -> Path:
        filename = ensure_suffix(filename, ".py")
        return Path(__file__).parent / "testdata/dataclasses" / filename

    return inner
