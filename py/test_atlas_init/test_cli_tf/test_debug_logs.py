from collections import defaultdict
import json
import logging
from os import getenv
from pathlib import Path
from atlas_init.cli_tf.debug_logs import SDKRoundtrip, parse_http_requests
from atlas_init.cli_tf.debug_logs_test_data import ApiSpecPath, create_test_data
from atlas_init.cli_tf.schema_v2_api_parsing import OpenapiSchema
from model_lib import dump, parse_model
import pytest

logger = logging.getLogger(__name__)


@pytest.fixture
def log_file_text() -> str:
    path = getenv("TF_LOG_FILE_PATH")
    if not path:
        pytest.skip("needs os.environ[TF_LOG_FILE_PATH]")
    return Path(path).read_text()


_seen_response_texts = set()


def log_roundtrips(roundtrips: list[SDKRoundtrip]):
    for rt in roundtrips:
        # if rt.request.method == "GET":
        #     continue
        # if rt.request.path.endswith(":validate"):
        #     continue
        if rt.response.text in _seen_response_texts:
            continue
        _seen_response_texts.add(rt.response.text)
        logger.info(
            f"\n{rt.request.method} {rt.request.path}\n{rt.request.text}\n{rt.response.status}-{rt.response.status_text}\n{rt.response.text}"
        )
    unique_count = len(_seen_response_texts)
    logger.info(f"Unique response texts: {unique_count}")


@pytest.fixture
def api_spec_paths(sdk_repo_path):
    api_spec_path = sdk_repo_path / "openapi/atlas-api-transformed.yaml"
    model = parse_model(api_spec_path, t=OpenapiSchema)
    paths: dict[str, list[ApiSpecPath]] = defaultdict(list)
    for path, path_dict in model.paths.items():
        for method in path_dict:
            paths[method.upper()].append(ApiSpecPath(path=path))
    return paths


def test_parse_http_requests(log_file_text, api_spec_paths, file_regression):
    assert len(api_spec_paths) == 5
    roundtrips = parse_http_requests(log_file_text)
    assert len(roundtrips) == 35
    # log_roundtrips(roundtrips)
    data = create_test_data(
        roundtrips,
        api_spec_paths,
        is_diff=lambda rt: rt.request.method in {"POST", "PUT", "PATCH"}
        and not rt.request.path.endswith(":validate"),
    )
    # avoid anchors
    data_yaml = dump(json.loads(dump(data, "json")), "yaml")
    file_regression.check(data_yaml, extension=".yaml")
