import logging
from typing import Any, TypeAlias

from model_lib import Event, parse_payload
from pydantic import constr
from zero_3rdparty.iter_utils import key_equal_value_to_dict

logger = logging.getLogger(__name__)
SdkVersion: TypeAlias = constr(pattern="v\d{11}")  # type: ignore
SDK_VERSION_HELP = "e.g., v20231115008 in go.mongodb.org/atlas-sdk/XXXX/admin"


class SdkVersionUpgrade(Event):
    old: SdkVersion
    new: SdkVersion



def parse_key_values(params: list[str]) -> dict[str, str]:
    return key_equal_value_to_dict(params)


def parse_key_values_any(params: list[str]) -> dict[str, Any]:
    str_dict = parse_key_values(params)
    return {
        k: parse_payload(v) if v.startswith(("{", "[")) else v
        for k, v in str_dict.items()
    }
