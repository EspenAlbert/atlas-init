from typing import Any

import typer
from model_lib import parse_payload
from zero_3rdparty.iter_utils import key_equal_value_to_dict

option_sdk_repo_path = typer.Option("", "-sdk", "--sdk-repo-path", help="the path to the sdk repo")


def parse_key_values(params: list[str]) -> dict[str, str]:
    return key_equal_value_to_dict(params)


def parse_key_values_any(params: list[str]) -> dict[str, Any]:
    str_dict = parse_key_values(params)
    return {k: parse_payload(v) if v.startswith(("{", "[")) else v for k, v in str_dict.items()}
