import logging
from enum import StrEnum
from pathlib import Path
from typing import ClassVar

from model_lib import Entity, parse_payload
from pydantic import model_validator
from zero_3rdparty.dict_nested import read_nested_or_none
from zero_3rdparty.str_utils import ensure_prefix

from atlas_init.cloud.aws import REGIONS, AwsRegion
from atlas_init.humps import pascalize
from atlas_init.repos.path import current_dir

logger = logging.getLogger(__name__)


def cfn_examples_dir(repo_path: Path) -> Path:
    return repo_path / "examples"


def infer_cfn_type_name() -> str:
    cwd = current_dir()
    for json_path in cwd.glob("*.json"):
        parsed = parse_payload(json_path)
        if type_name := read_nested_or_none(parsed, "typeName"):
            assert isinstance(type_name, str)
            return type_name
    raise ValueError(f"unable to infer cfn type name in {cwd}")


class CfnType(Entity):
    MONGODB_ATLAS_CFN_TYPE_PREFIX: ClassVar[str] = "MongoDB::Atlas::"

    type_name: str
    region_filter: AwsRegion | None = None

    @classmethod
    def validate_type_region(cls, type_name: str, region: str) -> tuple[str, str | None]:
        instance = CfnType(type_name=type_name, region_filter=region or None)
        return instance.type_name, instance.region_filter

    @model_validator(mode="after")
    def ensure_type_name_prefix(self):
        self.type_name = ensure_prefix(pascalize(self.type_name), self.MONGODB_ATLAS_CFN_TYPE_PREFIX)
        return self

    @classmethod
    def resource_name(cls, type_name: str) -> str:
        return type_name.removeprefix(cls.MONGODB_ATLAS_CFN_TYPE_PREFIX).lower()


class Operation(StrEnum):
    DELETE = "delete"
    CREATE = "create"
    UPDATE = "update"


class CfnOperation(Entity):
    operaton: Operation


def cfn_type_normalized(type_name: str) -> str:
    return type_name.removeprefix(CfnType.MONGODB_ATLAS_CFN_TYPE_PREFIX).lower()


class CfnTemplateParser(Entity):
    path: Path


def validate_type_name_regions(type_name: str, region_filter: str) -> tuple[str, list[str]]:
    type_name, region_filter = CfnType.validate_type_region(type_name, region_filter)  # type: ignore
    region_filter = region_filter or ""
    if region_filter:
        logger.info(f"{type_name} in region {region_filter}")
        regions = [region_filter]
    else:
        regions = REGIONS
        logger.info(f"{type_name} in ALL regions: {regions}")
    return type_name, regions  # type: ignore
