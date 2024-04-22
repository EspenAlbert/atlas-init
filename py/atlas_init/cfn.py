from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from functools import lru_cache
from boto3.session import Session
import logging
from mypy_boto3_cloudformation import CloudFormationClient
from zero_3rdparty.iter_utils import flat_map, group_by_once

from atlas_init.rich_log import configure_logging

logger = logging.getLogger(__name__)
REGIONS = "af-south-1,ap-east-1,ap-northeast-1,ap-northeast-2,ap-northeast-3,ap-south-1,ap-southeast-1,ap-southeast-2,ap-southeast-3,ca-central-1,eu-central-1,eu-north-1,eu-south-1,eu-west-1,eu-west-2,eu-west-3,me-south-1,sa-east-1,us-east-1,us-east-2,us-west-1,us-west-2,ap-south-2,ap-southeast-4,eu-central-2,eu-south-2,me-central-1,il-central-1".split(
    ","
)
EARLY_DATETIME = datetime(year=1990, month=1, day=1, tzinfo=timezone.utc)
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


@lru_cache
def cloud_formation_client(region_name: str = "") -> CloudFormationClient:
    return Session(region_name=region_name).client("cloudformation")  # type: ignore


def deregister_cfn_resource_type(
    type_name: str, deregister: bool, region_filter: str | None = None
):
    for region in REGIONS:
        if region_filter and region != region_filter:
            continue
        try:
            default_version_arn = None
            client = cloud_formation_client(region)
            for version in client.list_type_versions(
                Type="RESOURCE", TypeName=type_name
            )["TypeVersionSummaries"]:
                logger.info(f"found version: {version} for {type_name} in {region}")
                if not deregister:
                    continue
                arn = version["Arn"]
                if version["IsDefaultVersion"]:
                    default_version_arn = arn.rsplit("/", maxsplit=1)[0]
                else:
                    logger.info(f"deregistering: {arn}")
                    client.deregister_type(Arn=arn)
            if default_version_arn is not None:
                logger.info(f"deregistering default-arn: {arn}")
                client.deregister_type(Arn=default_version_arn)
        except Exception as e:
            if "The type does not exist" in repr(e):
                logger.info(f"type={type_name} not found in {region}")
                continue
            raise e


def delete_role_stack(type_name: str, region_name: str) -> None:
    client = cloud_formation_client(region_name)
    stack_name = type_name.replace("::", "-").lower() + "-role-stack"
    logger.warning(f"deleting stack {stack_name} in region={region_name}")
    client.update_termination_protection(
        EnableTerminationProtection=False, StackName=stack_name
    )
    client.delete_stack(StackName=stack_name)


iam_policy = """\
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Action": [
                "secretsmanager:GetSecretValue"
            ],
            "Resource": "*",
            "Effect": "Allow"
        }
    ]
}"""
iam_trust_policy = """\
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Principal": {
                "Service": [
                    "cloudformation.amazonaws.com",
                    "resources.cloudformation.amazonaws.com",
                    "lambda.amazonaws.com"
                ]
            },
            "Action": "sts:AssumeRole"
        }
    ]
}"""


def print_version_regions(type_name: str) -> None:
    version_regions = get_last_version_all_regions(type_name)
    if regions_with_no_version := version_regions.pop(None, []):
        logger.warning(f"no version for {type_name} found in {regions_with_no_version}")
    for version in sorted(version_regions.keys()):  # type: ignore
        regions = sorted(version_regions[version])
        regions_comma_separated = ",".join(regions)
        logger.info(f"'{version}' is latest in {regions_comma_separated}\ncontinents:")
        for continent, cont_regions in group_by_once(
            regions, key=region_continent
        ).items():
            continent_regions = ", ".join(sorted(cont_regions))
            logger.info(f"continent={continent}: {continent_regions}")


def get_last_version_all_regions(type_name: str) -> dict[str | None, list[str]]:
    futures = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        for region in REGIONS:
            future = pool.submit(get_last_version, type_name, region)
            futures[future] = region
        done, not_done = wait(futures.keys(), timeout=300)
        for f in not_done:
            logger.warning(f"timeout to find version in region = {futures[f]}")
    version_regions: dict[str | None, list[str]] = defaultdict(list)
    for f in done:
        region: str = futures[f]
        try:
            version = f.result()
        except Exception as e:
            logger.exception(e)
            logger.exception(f"failed to find version in region = {region}, error 👆")
            continue
        version_regions[version].append(region)
    return version_regions


def get_last_version(type_name: str, region: str) -> str | None:
    client: CloudFormationClient = cloud_formation_client(region)
    prefix = type_name
    logger.info(f"finding public 3rd party for '{prefix}' in {region}")
    # todo: Clean me up, and use this to find the arn
    # can also use "IsActivated" to be idempotent, and double-check the "LatestPublicVersion" and "LastUpdated"

    # todo: can use the static  arn:aws:iam::358363220050:role/mongodb-atlas-streamconnection-role-s-ExecutionRole-L8Pmt3uDFonT
    # but most likely will prefer to create this manually too

    public_types = client.list_types(
        Visibility="PUBLIC",
        Filters={"Category": "THIRD_PARTY", "TypeNamePrefix": prefix},
        MaxResults=100,
    )
    next_token = public_types["NextToken"]
    for t in public_types["TypeSummaries"]:
        logger.info(t)

    updated_version: list[tuple[datetime, str]] = []
    while next_token:
        public_types2 = client.list_types(
            Visibility="PUBLIC",
            Filters={"Category": "THIRD_PARTY", "TypeNamePrefix": prefix},
            MaxResults=100,
            NextToken=next_token,
        )
        next_token = public_types2.get("NextToken", "")
        for t in public_types2["TypeSummaries"]:
            last_updated = t.get("LastUpdated", EARLY_DATETIME)
            last_version = t.get("LatestPublicVersion", "unknown-version")
            updated_version.append((last_updated, last_version))
            logger.debug(f"{last_version} published @ {last_updated}")
    if not updated_version:
        logger.warning(f"no version for {type_name} in region {region}")
        return None
    return sorted(updated_version)[-1][1]


def activate_resource_type(type_name: str, region: str):
    client = cloud_formation_client(region)
    raise NotImplementedError
    # response = client.activate_type(
    #     Type="RESOURCE",
    #     PublicTypeArn="arn:aws:cloudformation:eu-south-2::type/resource/bb989456c78c398a858fef18f2ca1bfc1fbba082/MongoDB-Atlas-StreamConnection",
    #     ExecutionRoleArn="arn:aws:iam::358363220050:role/mongodb-atlas-streamconnection-role-s-ExecutionRole-L8Pmt3uDFonT"
    # )
    # logger.info(f"activate response: {response}")


if __name__ == "__main__":
    # deregister_cfn_resource_type("MongoDB::Atlas::StreamConnection", deregister=True)
    configure_logging()
    deregister_cfn_resource_type(
        "MongoDB::Atlas::Project", deregister=True, region_filter="us-east-1"
    )
    # activate_resource_type("MongoDB::Atlas::StreamConnection", "eu-south-2")
    # get_last_version("MongoDB::Atlas::Project", "eu-south-2")
    # print_version_regions("MongoDB::Atlas::Project")
