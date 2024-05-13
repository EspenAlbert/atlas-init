from typing import Annotated, TypeAlias
import stringcase
from pydantic import AfterValidator, ConfigDict
from zero_3rdparty.iter_utils import flat_map

PascalAlias = ConfigDict(alias_generator=stringcase.pascalcase, populate_by_name=True)
REGIONS = "af-south-1,ap-east-1,ap-northeast-1,ap-northeast-2,ap-northeast-3,ap-south-1,ap-southeast-1,ap-southeast-2,ap-southeast-3,ca-central-1,eu-central-1,eu-north-1,eu-south-1,eu-west-1,eu-west-2,eu-west-3,me-south-1,sa-east-1,us-east-1,us-east-2,us-west-1,us-west-2,ap-south-2,ap-southeast-4,eu-central-2,eu-south-2,me-central-1,il-central-1".split(
    ","
)
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
    """based on: https://www.mongodb.com/docs/atlas/reference/amazon-aws/"""
    prefix = region.split("-", maxsplit=1)[0]
    return REGION_PREFIX_CONTINENT.get(prefix, "UNKNOWN_CONTINENT")


def check_region_found(region: str) -> str:
    if region not in REGIONS:
        raise ValueError(f"unknown region: {region}")
    return region


AwsRegion: TypeAlias = Annotated[str, AfterValidator(check_region_found)]
