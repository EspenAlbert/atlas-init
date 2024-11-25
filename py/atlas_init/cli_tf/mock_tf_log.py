import json
import logging
from pathlib import Path
from typing import Self

import typer
from model_lib import Entity, dump
from pydantic import Field, model_validator
from zero_3rdparty import file_utils

from atlas_init.cli_args import option_sdk_repo_path
from atlas_init.cli_tf.debug_logs import (
    SDKRoundtrip,
    parse_http_requests,
    parse_test_name,
)
from atlas_init.cli_tf.debug_logs_test_data import create_mock_data, default_is_diff
from atlas_init.repos.go_sdk import parse_api_spec_paths

logger = logging.getLogger(__name__)


class MockTFLog(Entity):
    log_path: Path
    output_dir: Path
    sdk_path: Path
    diff_skip_suffixes: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def ensure_paths_exist(self) -> Self:
        if not self.log_path.exists():
            raise ValueError(f"log_path: {self.log_path} doesn't exist")
        if not self.sdk_path.exists():
            raise ValueError(f"sdk_path: {self.sdk_path} doesn't exist")
        if not self.output_dir.exists():
            raise ValueError(f"output_dir: {self.output_dir} doesn't exist")
        assert self.output_dir.name == "testdata", "output_path should be a directory named testdata"
        return self

    def differ(self, rt: SDKRoundtrip) -> bool:
        return default_is_diff(rt) and not any(rt.request.path.endswith(suffix) for suffix in self.diff_skip_suffixes)


def mock_tf_log(req: MockTFLog) -> None:
    log_file_text = req.log_path.read_text()
    test_name = parse_test_name(log_file_text)
    roundtrips = parse_http_requests(log_file_text)
    api_spec_paths = parse_api_spec_paths(req.sdk_path)
    data = create_mock_data(
        roundtrips,
        api_spec_paths,
        is_diff=req.differ,
    )
    # avoid anchors
    data_yaml = dump(json.loads(dump(data, "json")), "yaml")
    output_path = req.output_dir / f"{test_name}.yaml"
    logger.info(f"Writing to {output_path}")
    file_utils.ensure_parents_write_text(output_path, data_yaml)


def mock_tf_log_cmd(
    log_path: str = typer.Argument(..., help="the path to the log file generated with TF_LOG_PATH"),
    sdk_repo_path_str: str = option_sdk_repo_path,
    output_testdir: str = typer.Option(
        "",
        "-o",
        "--output-testdir",
        help="the path to the output test directory, for example: internal/service/advancedclustertpf/testdata/",
    ),
    diff_skip_suffixes: list[str] = typer.Option(..., "-s", "--skip-suffixes", default_factory=list),
):
    cwd = Path.cwd()
    default_sdk_path = cwd.parent / "atlas-sdk-go"
    default_testdir = cwd.parent / "testdata"
    event_in = MockTFLog(
        log_path=Path(log_path),
        output_dir=Path(output_testdir) if output_testdir else default_testdir,
        sdk_path=Path(sdk_repo_path_str) if sdk_repo_path_str else default_sdk_path,
        diff_skip_suffixes=diff_skip_suffixes,
    )
    mock_tf_log(event_in)
