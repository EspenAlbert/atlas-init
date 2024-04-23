import logging
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import datetime, timezone
from functools import lru_cache, total_ordering
from typing import Sequence

from boto3.session import Session
import botocore.exceptions
from model_lib import Event
from mypy_boto3_cloudformation import CloudFormationClient
from mypy_boto3_cloudformation.type_defs import ParameterTypeDef
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed
from zero_3rdparty.iter_utils import group_by_once

from atlas_init.cli_args import REGIONS, region_continent
from atlas_init.constants import PascalAlias
from atlas_init.rich_log import configure_logging

logger = logging.getLogger(__name__)
EARLY_DATETIME = datetime(year=1990, month=1, day=1, tzinfo=timezone.utc)


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
    stack_name = type_name.replace("::", "-").lower() + "-role-stack"
    delete_stack(region_name, stack_name)


def delete_stack(region_name: str, stack_name: str):
    client = cloud_formation_client(region_name)
    logger.warning(f"deleting stack {stack_name} in region={region_name}")
    try:
        client.update_termination_protection(
            EnableTerminationProtection=False, StackName=stack_name
        )
    except Exception as e:
        if "does not exist" in repr(e):
            logger.warning(f"stack {stack_name} not found")
            return
        raise e
    client.delete_stack(StackName=stack_name)
    wait_on_stack_ok(stack_name, region_name, expect_not_found=True)

def create_stack(
    stack_name: str,
    template_str: str,
    region_name: str,
    role_arn: str,
    parameters: Sequence[ParameterTypeDef],
):
    client = cloud_formation_client(region_name)
    stack_id = client.create_stack(
        StackName=stack_name,
        TemplateBody=template_str,
        Parameters=parameters,
        RoleARN=role_arn,
    )
    logger.info(
        f"stack with name: {stack_name} created in {region_name} has id: {stack_id['StackId']}"
    )
    wait_on_stack_ok(stack_name, region_name)


def update_stack(
    stack_name: str,
    region_name: str,
    role_arn: str,
    parameters: Sequence[ParameterTypeDef],
):
    client = cloud_formation_client(region_name)
    update = client.update_stack(
        StackName=stack_name,
        UsePreviousTemplate=True,
        Parameters=parameters,
        RoleARN=role_arn,
    )
    logger.info(
        f"stack with name: {stack_name} updated {region_name} has id: {update['StackId']}"
    )
    wait_on_stack_ok(stack_name, region_name)


class StackBaseError(Exception):
    def __init__(self, status: str, timestamp: datetime, status_reason: str) -> None:
        super().__init__(status, timestamp, status_reason)
        self.status = status
        self.timestamp = timestamp
        self.status_reason = status_reason


class StackInProgress(StackBaseError):
    pass


class StackError(StackBaseError):
    pass


@total_ordering
class StackEvent(Event):
    model_config = PascalAlias
    logical_resource_id: str
    timestamp: datetime
    resource_status: str
    resource_status_reason: str = ""

    @property
    def in_progress(self) -> bool:
        return self.resource_status.endswith("IN_PROGRESS")

    @property
    def is_error(self) -> bool:
        return self.resource_status.endswith("FAILED")

    def __lt__(self, other) -> bool:
        if not isinstance(other, StackEvent):
            raise TypeError
        return self.timestamp < other.timestamp


class StackEvents(Event):
    model_config = PascalAlias
    stack_events: list[StackEvent]

    def current_stack_event(self, stack_name: str) -> StackEvent:
        sorted_events = sorted(self.stack_events)
        for event in reversed(sorted_events):
            if event.logical_resource_id == stack_name:
                return event
        raise ValueError(f"no events found for {stack_name}")


@retry(
    stop=stop_after_attempt(20),
    wait=wait_fixed(6),
    retry=retry_if_exception_type(StackInProgress),
    reraise=True,
)
def wait_on_stack_ok(stack_name: str, region_name: str, expect_not_found: bool = False) -> None:
    client = cloud_formation_client(region_name)
    try:
        response = client.describe_stack_events(StackName=stack_name)
    except botocore.exceptions.ClientError as e:
        if not expect_not_found:
            raise e
        error_message = e.response.get("Error", {}).get("Message", "")
        if "does not exist" not in error_message:
            raise e
        return None
    parsed = StackEvents(stack_events=response.get("StackEvents", []))  # type: ignore
    current_event = parsed.current_stack_event(stack_name)
    if current_event.in_progress:
        logger.info(f"stack in progress {stack_name} {current_event.resource_status}")
        raise StackInProgress(
            current_event.resource_status,
            current_event.timestamp,
            current_event.resource_status_reason,
        )
    elif current_event.is_error:
        raise StackError(
            current_event.resource_status,
            current_event.timestamp,
            current_event.resource_status_reason,
        )
    logger.info(f"stack is ready {stack_name} {current_event.resource_status} ✅")
    return None


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
            future = pool.submit(get_last_cfn_type, type_name, region)
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


@total_ordering
class CfnTypeDetails(Event):
    last_updated: datetime
    version: str
    type_name: str
    type_arn: str

    def __lt__(self, other) -> bool:
        if not isinstance(other, CfnTypeDetails):
            raise TypeError
        return self.last_updated < other.last_updated


def get_last_cfn_type(
    type_name: str, region: str, is_third_party: bool = False
) -> None | CfnTypeDetails:
    client: CloudFormationClient = cloud_formation_client(region)
    prefix = type_name
    logger.info(f"finding public 3rd party for '{prefix}' in {region}")
    visibility = "PUBLIC" if is_third_party else "PRIVATE"
    category = "THIRD_PARTY" if is_third_party else "REGISTERED"
    type_details: list[CfnTypeDetails] = []
    kwargs = dict(
        Visibility=visibility,
        Filters={"Category": category, "TypeNamePrefix": prefix},
        MaxResults=100,
    )
    next_token = ""
    for _ in range(100):
        types_response = client.list_types(**kwargs)  # type: ignore
        next_token = types_response.get("NextToken", "")
        kwargs["NextToken"] = next_token
        for t in types_response["TypeSummaries"]:
            last_updated = t.get("LastUpdated", EARLY_DATETIME)
            last_version = t.get("LatestPublicVersion", "unknown-version")
            arn = t.get("TypeArn", "unknown_arn")
            detail = CfnTypeDetails(
                last_updated=last_updated,
                version=last_version,
                type_name=t.get("TypeName", type_name),
                type_arn=arn,
            )
            type_details.append(detail)
            logger.debug(f"{last_version} published @ {last_updated}")
        if not next_token:
            break
    if not type_details:
        logger.warning(f"no version for {type_name} in region {region}")
        return None
    return sorted(type_details)[-1]


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
