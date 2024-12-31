import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, wait
from pathlib import Path
from typing import Annotated, TypeVar

import stringcase
from pydantic import AfterValidator, ConfigDict
from zero_3rdparty.iter_utils import flat_map
from zero_3rdparty.object_name import as_name

from atlas_init.cli_helper.run import run_binary_command_is_ok
from atlas_init.cli_root import is_dry_run

logger = logging.getLogger(__name__)
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
        [[(prefix, continent) for prefix in prefixes] for continent, prefixes in REGION_CONTINENT_PREFIXES.items()]
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


AwsRegion = Annotated[str, AfterValidator(check_region_found)]
T = TypeVar("T")


def run_in_regions(call: Callable[[str], T], regions: list[str] | None = None) -> dict[str, T]:  # type: ignore
    futures = {}
    name = as_name(call)
    regions: list[str] = regions or REGIONS  # type: ignore
    with ThreadPoolExecutor(max_workers=10) as pool:
        for region in regions:
            future = pool.submit(call, region)
            futures[future] = region
        done, not_done = wait(futures.keys(), timeout=300)
        for f in not_done:
            logger.warning(f"timeout for {name} in region = {futures[f]}")
    region_responses: dict[str, T] = {}
    for f in done:
        region: str = futures[f]
        try:
            response = f.result()
            region_responses[region] = response
        except Exception:
            logger.exception(f"failed to call {name} in region = {region}, error 👆")
    return region_responses


def upload_to_s3(profile_path: Path, s3_bucket: str, s3_prefix: str = ""):
    profiles_path = profile_path.parent
    assert profiles_path.name == "profiles"
    excluded = [".DS_Store", ".terraform/*"]
    excluded_str = " ".join([f'--exclude "{pattern}"' for pattern in excluded])
    assert run_binary_command_is_ok(
        "aws",
        f"s3 sync {profile_path.name} s3://{s3_bucket}/{s3_prefix}/profiles/{profile_path.name} {excluded_str}",
        profiles_path,
        logger=logger,
        dry_run=is_dry_run(),
    )


def download_from_s3(profile_path: Path, s3_bucket: str, s3_prefix: str = ""):
    profiles_path = profile_path.parent
    assert profiles_path.name == "profiles"
    assert run_binary_command_is_ok(
        "aws",
        f"s3 sync s3://{s3_bucket}/{s3_prefix}profiles/{profile_path.name} {profile_path.name}/",
        profiles_path,
        logger=logger,
        dry_run=is_dry_run(),
    )
