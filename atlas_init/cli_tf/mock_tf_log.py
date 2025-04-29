import json
import logging
import time
from collections.abc import Callable
from io import StringIO
from pathlib import Path
from typing import Self

import typer
import yaml
from model_lib import Entity
from pydantic import Field, model_validator
from zero_3rdparty import file_utils

from atlas_init.cli_args import option_sdk_repo_path
from atlas_init.cli_tf.debug_logs import (
    SDKRoundtrip,
    parse_http_requests,
    parse_test_name,
)
from atlas_init.cli_tf.debug_logs_test_data import (
    RTModifier,
    create_mock_data,
    default_is_diff,
)
from atlas_init.cli_tf.debug_logs_test_data_package_config import (
    package_modifiers,
    package_must_substrings,
    package_skip_suffixes,
)
from atlas_init.repos.go_sdk import (
    api_spec_path_transformed,
    download_admin_api,
    parse_api_spec_paths,
)
from atlas_init.settings.env_vars import init_settings

logger = logging.getLogger(__name__)


class MockTFLog(Entity):
    log_path: Path
    output_dir: Path
    admin_api_path: Path
    diff_skip_suffixes: list[str] = Field(default_factory=list)
    diff_must_substrings: list[str] = Field(default_factory=list)
    keep_duplicates: bool = False
    modifiers: list[RTModifier] = Field(default_factory=list)
    package_name: str = ""
    log_diff_roundtrips: bool = False
    skip_default_package_config: bool = False

    @model_validator(mode="after")
    def ensure_paths_exist(self) -> Self:
        if not self.log_path.exists():
            raise ValueError(f"log_path: '{self.log_path}' doesn't exist")
        if not self.admin_api_path.exists():
            raise ValueError(f"admin_api_path: '{self.admin_api_path}' doesn't exist")
        if not self.output_dir.exists():
            raise ValueError(f"output_dir: '{self.output_dir}' doesn't exist")
        assert self.output_dir.name == "testdata", "output_path should be a directory named testdata"
        if (package_name := self.package_name) and not self.skip_default_package_config:
            self.modifiers.extend(package_modifiers(package_name))
            self.diff_skip_suffixes.extend(package_skip_suffixes(package_name))
            self.diff_must_substrings.extend(package_must_substrings(package_name))
        return self

    def differ(self, rt: SDKRoundtrip) -> bool:
        is_diff = default_is_diff(rt) and not any(
            rt.request.path.endswith(suffix) for suffix in self.diff_skip_suffixes
        )
        if is_diff and self.diff_must_substrings:
            return is_diff and all(substring in rt.request.path for substring in self.diff_must_substrings)
        return is_diff


def mock_tf_log(req: MockTFLog) -> Path:
    log_file_text = req.log_path.read_text()
    test_name = parse_test_name(log_file_text)
    roundtrips = parse_http_requests(log_file_text)
    logger.info(f"Found #{len(roundtrips)} roundtrips")
    if req.log_diff_roundtrips:
        log_diff_roundtrips(roundtrips, req.differ)
    api_spec_paths = parse_api_spec_paths(req.admin_api_path)
    data = create_mock_data(
        roundtrips,
        api_spec_paths,
        is_diff=req.differ,
        prune_duplicates=not req.keep_duplicates,
        modifiers=req.modifiers,
    )
    # avoid anchors
    data_json = data.model_dump_json(exclude_none=True)
    data_parsed = json.loads(data_json)
    s = StringIO()
    yaml.safe_dump(
        data_parsed,
        s,
        default_flow_style=False,
        width=100_000,
        allow_unicode=True,
        sort_keys=False,
    )
    data_yaml = s.getvalue()
    test_name = test_name.replace("TestAcc", "TestMock")
    output_path = req.output_dir / f"{test_name}.yaml"
    logger.info(f"Variables found {data.variables}")
    logger.info(f"Writing to {output_path}")
    file_utils.ensure_parents_write_text(output_path, data_yaml)
    return output_path


def mock_tf_log_cmd(
    log_path: str = typer.Argument(..., help="the path to the log file generated with TF_LOG_PATH"),
    output_testdir: str = typer.Option(
        "",
        "-o",
        "--output-testdir",
        help="the path to the output test directory, for example: internal/service/advancedclustertpf/testdata/, uses $(cwd)/testdata by default",
    ),
    sdk_repo_path_str: str = option_sdk_repo_path,
    sdk_branch: str = typer.Option("main", "-b", "--branch", help="the branch for downloading openapi spec"),
    admin_api_path: str = typer.Option(
        "", "-a", "--admin-api-path", help="the path to store/download the openapi spec"
    ),
    diff_skip_suffixes: list[str] = typer.Option(..., "-s", "--skip-suffixes", default_factory=list),
    keep_duplicates: bool = typer.Option(False, "-keep", "--keep-duplicates", help="keep duplicate requests"),
    log_diff_roundtrips: bool = typer.Option(
        False, "-l", "--log-diff-roundtrips", help="print out the roundtrips used in diffs"
    ),
    package_name: str = typer.Option("-p", "--package-name", prompt=True, help="the package name to use for modifiers"),
):
    cwd = Path.cwd()
    default_testdir = cwd / "testdata"
    resolved_admin_api_path = resolve_admin_api_path(sdk_repo_path_str, sdk_branch, admin_api_path)
    event_in = MockTFLog(
        log_path=Path(log_path),
        output_dir=Path(output_testdir) if output_testdir else default_testdir,
        admin_api_path=resolved_admin_api_path,
        diff_skip_suffixes=diff_skip_suffixes,
        keep_duplicates=keep_duplicates,
        log_diff_roundtrips=log_diff_roundtrips,
        package_name=package_name,
    )
    mock_tf_log(event_in)


def is_cache_up_to_date(cache_path: Path, cache_ttl: int) -> bool:
    if cache_path.exists():
        modified_ts = file_utils.file_modified_time(cache_path)
        if modified_ts > time.time() - cache_ttl:
            logger.info(f"using cached admin api: {cache_path} downloaded {time.time() - modified_ts:.0f}s ago")
            return True
    return False


def resolve_admin_api_path(sdk_repo_path_str: str = "", sdk_branch: str = "main", admin_api_path: str = "") -> Path:
    if admin_api_path:
        resolved_admin_api_path = Path(admin_api_path)
        if not resolved_admin_api_path.exists():
            download_admin_api(resolved_admin_api_path, sdk_branch)
    elif sdk_repo_path_str:
        sdk_repo_path = Path(sdk_repo_path_str)
        assert sdk_repo_path.exists(), f"not found sdk_repo_path={sdk_repo_path}"
        resolved_admin_api_path = api_spec_path_transformed(sdk_repo_path)
    else:
        settings = init_settings()
        resolved_admin_api_path = settings.atlas_atlas_api_transformed_yaml
        if not is_cache_up_to_date(resolved_admin_api_path, 3600):
            download_admin_api(resolved_admin_api_path, sdk_branch)
    assert resolved_admin_api_path.exists(), f"unable to resolve admin_api_path={resolved_admin_api_path}"
    assert resolved_admin_api_path.is_file(), f"not a file admin_api_path={resolved_admin_api_path}"
    return resolved_admin_api_path


def log_diff_roundtrips(roundtrips: list[SDKRoundtrip], differ: Callable[[SDKRoundtrip], bool] | None = None):
    differ = differ or default_is_diff
    diff_count = 0
    step_nr = 0
    for rt in roundtrips:
        if not differ(rt):
            continue
        if rt.step_number != step_nr:
            logger.info(f"{'-' * 80}\nStep {rt.step_number}")
            step_nr = rt.step_number
        diff_count += 1
        logger.info(
            f"\n{rt.request.method} {rt.request.path} {rt.version}\n{rt.request.text}\n{rt.response.status}-{rt.response.status_text}\n{rt.response.text}"
        )
    logger.info(f"Diffable requests: {diff_count}")
