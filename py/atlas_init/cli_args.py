from enum import StrEnum
from pathlib import Path
from typing import Annotated, ClassVar, TypeAlias

from model_lib import Entity, Event
from pydantic import AfterValidator, constr, model_validator
from zero_3rdparty.iter_utils import flat_map, key_equal_value_to_dict
from zero_3rdparty.str_utils import ensure_prefix

SdkVersion: TypeAlias = constr(pattern="v\d{11}")  # type: ignore
SDK_VERSION_HELP = "e.g., v20231115008 in go.mongodb.org/atlas-sdk/XXXX/admin"


class SdkVersionUpgrade(Event):
    old: SdkVersion
    new: SdkVersion

def check_region_found(region: str) -> str:
    if region not in REGIONS:
        raise ValueError(f"unknown region: {region}")
    return region

Region: TypeAlias = Annotated[str, AfterValidator(check_region_found)]

def parse_key_values(params: list[str]) -> dict[str, str]:
    return key_equal_value_to_dict(params)

class CfnType(Entity):
    MONGODB_ATLAS_CFN_TYPE_PREFIX: ClassVar[str] = "MongoDB::Atlas::"

    type_name: str
    region_filter: Region

    @classmethod
    def validate_type_region(cls, type_name: str, region: str) -> tuple[str, str]:
        instance = CfnType(type_name=type_name, region_filter=region)
        return instance.type_name, instance.region_filter

    @model_validator(mode="after")
    def ensure_type_name_prefix(self):
        self.type_name = ensure_prefix(
            self.type_name.capitalize(), self.MONGODB_ATLAS_CFN_TYPE_PREFIX
        )
        return self


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


REGIONS = "af-south-1,ap-east-1,ap-northeast-1,ap-northeast-2,ap-northeast-3,ap-south-1,ap-southeast-1,ap-southeast-2,ap-southeast-3,ca-central-1,eu-central-1,eu-north-1,eu-south-1,eu-west-1,eu-west-2,eu-west-3,me-south-1,sa-east-1,us-east-1,us-east-2,us-west-1,us-west-2,ap-south-2,ap-southeast-4,eu-central-2,eu-south-2,me-central-1,il-central-1".split(
    ","
)
# based on: https://www.mongodb.com/docs/atlas/reference/amazon-aws/
REGION_CONTINENT_PREFIXES = {
    "Americas": ["us", "ca", "sa"],
    "Asia Pacific": ["ap"],
    "Europe": ["eu"],
    "Middle East and Africa": ["me", "af", "il"],
}
REGION_PREFIX_CONTINENT = dict(
    flat_map(
        [
            [(prefix, continent) for prefix in prefixes]
            for continent, prefixes in REGION_CONTINENT_PREFIXES.items()
        ]
    )
)


def region_continent(region: str) -> str:
    prefix = region.split("-", maxsplit=1)[0]
    return REGION_PREFIX_CONTINENT.get(prefix, "UNKNOWN_CONTINENT")
