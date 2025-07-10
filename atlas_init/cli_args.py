from __future__ import annotations
from typing import Any

from pydantic import BaseModel, DirectoryPath
import typer
from model_lib import parse_payload
from zero_3rdparty.iter_utils import key_equal_value_to_dict

ENV_VAR_SDK_REPO_PATH = "SDK_REPO_PATH"
option_sdk_repo_path = typer.Option(
    "", "-sdk", "--sdk-repo-path", help="the path to the sdk repo", envvar=ENV_VAR_SDK_REPO_PATH
)
option_mms_repo_path = typer.Option("", "--mms-path", help="Path to the mms directory", envvar="MMS_PATH")


class ParsedPaths(BaseModel):
    sdk_repo_path: DirectoryPath | None = None
    mms_repo_path: DirectoryPath | None = None

    @classmethod
    def from_strings(cls, *, sdk_repo_path_str: str = "", mms_path: str = "") -> ParsedPaths:
        return cls(
            sdk_repo_path=sdk_repo_path_str or None,  # type: ignore
            mms_repo_path=mms_path or None,  # type: ignore
        )


def parse_key_values(params: list[str]) -> dict[str, str]:
    return key_equal_value_to_dict(params)


def parse_key_values_any(params: list[str]) -> dict[str, Any]:
    str_dict = parse_key_values(params)
    return {k: parse_payload(v) if v.startswith(("{", "[")) else v for k, v in str_dict.items()}
