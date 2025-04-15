from __future__ import annotations

import logging
from collections import defaultdict
from collections.abc import Sequence
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import UTC, datetime
from functools import lru_cache, total_ordering
from pathlib import Path

import botocore.exceptions
import humanize
import typer
from boto3.session import Session
from model_lib import Event
from mypy_boto3_cloudformation import CloudFormationClient
from mypy_boto3_cloudformation.type_defs import ListTypesOutputTypeDef, ParameterTypeDef
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed
from zero_3rdparty.datetime_utils import utc_now
from zero_3rdparty.iter_utils import group_by_once

from atlas_init.cli_helper.run import run_command_is_ok
from atlas_init.cloud.aws import REGIONS, PascalAlias, region_continent
from atlas_init.settings.interactive import confirm

logger = logging.getLogger(__name__)
EARLY_DATETIME = datetime(year=1990, month=1, day=1, tzinfo=UTC)


@lru_cache
def cloud_formation_client(region_name: str = "") -> CloudFormationClient:
    return Session(region_name=region_name).client("cloudformation")  # type: ignore


def deregister_cfn_resource_type(type_name: str, deregister: bool, region_filter: str | None = None):
    for region in REGIONS:
        if region_filter and region != region_filter:
            continue
        try:
            default_version_arn = None
            client = cloud_formation_client(region)
            for version in client.list_type_versions(Type="RESOURCE", TypeName=type_name)["TypeVersionSummaries"]:
                logger.info(f"found version: {version} for {type_name} in {region}")
                if not deregister:
                    continue
                arn = version["Arn"]  # type: ignore
                if version["IsDefaultVersion"]:  # type: ignore
                    default_version_arn = arn.rsplit("/", maxsplit=1)[0]
                else:
                    logger.info(f"deregistering: {arn}")
                    client.deregister_type(Arn=arn)
            if default_version_arn is not None:
                logger.info(f"deregistering default-arn: {default_version_arn}")
                client.deregister_type(Arn=default_version_arn)
        except Exception as e:
            if "The type does not exist" in repr(e):
                logger.info(f"type={type_name} not found in {region}")
                continue
            raise


def deregister_arn(arn: str, region: str):
    client = cloud_formation_client(region)
    logger.warning(f"deregistering type {arn} in {region}")
    client.deregister_type(Arn=arn)


def deactivate_third_party_type(type_name: str, region_name: str, *, dry_run: bool = False) -> None | CfnTypeDetails:
    last_version = get_last_cfn_type(type_name, region=region_name, is_third_party=True)
    if not last_version:
        logger.info(f"no third party found in region {region_name}")
        return
    is_activated = last_version.is_activated
    logger.info(f"found {last_version.type_name} {last_version.version} in {region_name}, is_activated={is_activated}")
    if is_activated and not dry_run:
        deactivate_type(type_name=type_name, region=region_name)


def deactivate_type(type_name: str, region: str):
    client = cloud_formation_client(region)
    logger.warning(f"deactivating type {type_name} in {region}")
    client.deactivate_type(TypeName=type_name, Type="RESOURCE")


def delete_role_stack(type_name: str, region_name: str, role_arn: str = "") -> None:
    stack_name = type_name.replace("::", "-").lower() + "-role-stack"
    delete_stack(region_name, stack_name, role_arn)


def delete_stack(region_name: str, stack_name: str, role_arn: str = ""):
    client = cloud_formation_client(region_name)
    logger.warning(f"deleting stack {stack_name} in region={region_name}")
    try:
        client.update_termination_protection(EnableTerminationProtection=False, StackName=stack_name)
    except Exception as e:
        if "does not exist" in repr(e):
            logger.warning(f"stack {stack_name} not found")
            return
        raise
    client.delete_stack(StackName=stack_name, RoleARN=role_arn)
    wait_on_stack_ok(stack_name, region_name, expect_not_found=True)


def create_stack(
    stack_name: str,
    template_str: str,
    region_name: str,
    role_arn: str,
    parameters: Sequence[ParameterTypeDef],
    timeout_seconds: int = 300,
):
    client = cloud_formation_client(region_name)
    stack_id = client.create_stack(
        StackName=stack_name,
        TemplateBody=template_str,
        Parameters=parameters,
        RoleARN=role_arn,
    )
    logger.info(
        f"stack with name: {stack_name} created in {region_name} has id: {stack_id['StackId']} role_arn:{role_arn}"
    )
    wait_on_stack_ok(stack_name, region_name, timeout_seconds=timeout_seconds)


def update_stack(
    stack_name: str,
    template_str: str,
    region_name: str,
    role_arn: str,
    parameters: Sequence[ParameterTypeDef],
    timeout_seconds: int = 300,
):
    client = cloud_formation_client(region_name)
    update = client.update_stack(
        StackName=stack_name,
        TemplateBody=template_str,
        Parameters=parameters,
        RoleARN=role_arn,
    )
    logger.info(f"stack with name: {stack_name} updated {region_name} has id: {update['StackId']}")
    wait_on_stack_ok(stack_name, region_name, timeout_seconds=timeout_seconds)


class StackBaseError(Exception):
    def __init__(self, status: str, timestamp: datetime, status_reason: str) -> None:
        super().__init__(status, timestamp, status_reason)
        self.status = status
        self.timestamp = timestamp
        self.status_reason = status_reason


class StackInProgressError(StackBaseError):
    pass


class StackError(StackBaseError):
    def __init__(self, status: str, timestamp: datetime, status_reason: str, reasons: str) -> None:
        super().__init__(status, timestamp, status_reason)
        self.reasons = reasons


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

    def last_reason(self) -> str:
        for event in sorted(self.stack_events, reverse=True):
            if reason := event.resource_status_reason.strip():
                return reason
        return ""

    def multiple_reasons(self, max_reasons: int = 5) -> str:
        reasons = []
        for event in sorted(self.stack_events, reverse=True):
            if reason := event.resource_status_reason.strip():
                reason_number = len(reasons) + 1
                reasons.append(f"{reason_number}. {reason}")
                if reason_number >= max_reasons:
                    break
        return "\n".join(reasons)


def wait_on_stack_ok(
    stack_name: str,
    region_name: str,
    *,
    expect_not_found: bool = False,
    timeout_seconds: int = 300,
) -> None:
    attempts = timeout_seconds // 6

    @retry(
        stop=stop_after_attempt(attempts + 1),
        wait=wait_fixed(6),
        retry=retry_if_exception_type(StackInProgressError),
        reraise=True,
    )
    def _wait_on_stack_ok() -> None:
        client = cloud_formation_client(region_name)
        try:
            response = client.describe_stack_events(StackName=stack_name)
        except botocore.exceptions.ClientError as e:
            if not expect_not_found:
                raise
            error_message = e.response.get("Error", {}).get("Message", "")
            if "does not exist" not in error_message:
                raise
            return None
        parsed = StackEvents(stack_events=response.get("StackEvents", []))  # type: ignore
        current_event = parsed.current_stack_event(stack_name)
        if current_event.in_progress:
            logger.info(f"stack in progress {stack_name} {current_event.resource_status}")
            raise StackInProgressError(
                current_event.resource_status,
                current_event.timestamp,
                current_event.resource_status_reason,
            )
        if current_event.is_error:
            raise StackError(
                current_event.resource_status,
                current_event.timestamp,
                current_event.resource_status_reason,
                reasons=parsed.multiple_reasons(),
            )
        status = current_event.resource_status
        logger.info(f"stack is ready {stack_name} {status} ✅")
        if "ROLLBACK" in status:
            last_reason = parsed.multiple_reasons()
            logger.warning(f"stack did rollback, got: {current_event!r}\n{last_reason}")

        return None

    try:
        return _wait_on_stack_ok()
    except StackError as e:
        logger.warning(f"stack error {stack_name} {e.status} {e.status_reason}\n{e.reasons}")
        raise typer.Exit(1) from None


def print_version_regions(type_name: str) -> None:
    version_regions = get_last_version_all_regions(type_name)
    if regions_with_no_version := version_regions.pop(None, []):
        logger.warning(f"no version for {type_name} found in {regions_with_no_version}")
    for version in sorted(version_regions.keys()):  # type: ignore
        regions = sorted(version_regions[version])
        regions_comma_separated = ",".join(regions)
        logger.info(f"'{version}' is latest in {regions_comma_separated}\ncontinents:")
        for continent, cont_regions in group_by_once(regions, key=region_continent).items():
            continent_regions = ", ".join(sorted(cont_regions))
            logger.info(f"continent={continent}: {continent_regions}")


def get_last_version_all_regions(type_name: str) -> dict[str | None, list[str]]:
    futures = {}
    with ThreadPoolExecutor(max_workers=10) as pool:
        for region in REGIONS:
            future = pool.submit(get_last_cfn_type, type_name, region, is_third_party=True)
            futures[future] = region
        done, not_done = wait(futures.keys(), timeout=300)
        for f in not_done:
            logger.warning(f"timeout to find version in region = {futures[f]}")
    version_regions: dict[str | None, list[str]] = defaultdict(list)
    for f in done:
        region: str = futures[f]
        try:
            version = f.result()
        except Exception:
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
    is_activated: bool

    def __lt__(self, other) -> bool:
        if not isinstance(other, CfnTypeDetails):
            raise TypeError
        return self.last_updated < other.last_updated

    def seconds_since_update(self) -> float:
        return (utc_now() - self.last_updated).total_seconds()


def publish_cfn_type(region: str):
    client: CloudFormationClient = cloud_formation_client(region)
    client.publish_type()


def get_last_cfn_type(
    type_name: str, region: str, *, is_third_party: bool = False, force_version: str = ""
) -> None | CfnTypeDetails:
    client: CloudFormationClient = cloud_formation_client(region)
    prefix = type_name
    logger.info(f"finding public 3rd party for '{prefix}' in {region}")
    visibility = "PUBLIC" if is_third_party else "PRIVATE"
    category = "THIRD_PARTY" if is_third_party else "REGISTERED"
    type_details: list[CfnTypeDetails] = []
    kwargs = {
        "Visibility": visibility,
        "Filters": {"Category": category, "TypeNamePrefix": prefix},
        "MaxResults": 100,
    }
    next_token = ""  # nosec
    for _ in range(100):
        types_response: ListTypesOutputTypeDef = client.list_types(**kwargs)  # type: ignore
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
                is_activated=t.get("IsActivated", False),
            )
            if detail.type_name != type_name:
                continue
            type_details.append(detail)
            logger.debug(f"{last_version} published @ {last_updated}")
        if not next_token:
            break
    if not type_details:
        logger.warning(f"no version for {type_name} in region {region}")
        return None
    if force_version:
        for detail in type_details:
            if detail.version == force_version:
                return detail
        versions = [d.version for d in type_details]
        raise ValueError(f"unable to find version {force_version} for {type_name}, got {versions}")
    return sorted(type_details)[-1]


def activate_resource_type(details: CfnTypeDetails, region: str, execution_role_arn: str):
    client = cloud_formation_client(region)
    response = client.activate_type(
        Type="RESOURCE",
        PublicTypeArn=details.type_arn,
        ExecutionRoleArn=execution_role_arn,
    )
    logger.info(f"activate response: {response} role={execution_role_arn}")


def ensure_resource_type_activated(
    type_name: str,
    region: str,
    force_deregister: bool,
    is_interactive: bool,
    resource_path: Path,
    cfn_execution_role: str,
    force_version: str = "",
) -> None:
    cfn_type_details = get_last_cfn_type(type_name, region, is_third_party=False)
    logger.info(f"found cfn_type_details {cfn_type_details} for {type_name}")
    is_third_party = False
    if cfn_type_details is None:
        cfn_type_details = get_last_cfn_type(type_name, region, is_third_party=True)
        if cfn_type_details:
            is_third_party = True
            logger.warning(f"found 3rd party extension for cfn type {type_name} active")
    if force_version:
        if cfn_type_details and cfn_type_details.version == force_version:
            logger.info(f"version {force_version} already active")
            return
        force_deregister = True
    if cfn_type_details is not None and (cfn_type_details.seconds_since_update() > 3600 * 24 or force_deregister):
        outdated_warning = f"more than {humanize.naturaldelta(cfn_type_details.seconds_since_update())} since last update to {type_name} {cfn_type_details.version}"
        logger.warning(outdated_warning)
        if force_deregister or confirm(
            f"{outdated_warning}, should deregister?",
            is_interactive=is_interactive,
            default=True,
        ):
            if is_third_party:
                deactivate_third_party_type(type_name, region)
            else:
                deregister_cfn_resource_type(type_name, deregister=True, region_filter=region)
            cfn_type_details = None

    # assert cfn_type_details, f"no cfn_type_details found for {type_name}"
    # client = cloud_formation_client(region)
    # response = client.activate_type(
    #     Type="RESOURCE",
    #     # PublicTypeArn=cfn_type_details.type_arn.replace(":type/", "::type/"),
    #     PublicTypeArn="arn:aws:cloudformation:eu-south-2:358363220050::type/resource/MongoDB-Atlas-ResourcePolicy/00000001",
    #     ExecutionRoleArn=cfn_execution_role,
    #     LoggingConfig={"LogRoleArn": cfn_execution_role, "LogGroupName": "/apix/espen/cfn-test1"},
    # )
    # logger.info(f"activate response: {response}")
    submit_cmd = f"cfn submit --verbose --set-default --region {region} --role-arn {cfn_execution_role}"
    if (
        not force_version
        and cfn_type_details is None
        and confirm(
            f"No existing {type_name} found, ok to run:\n{submit_cmd}\nsubmit?",
            is_interactive=is_interactive,
            default=True,
        )
    ):
        assert run_command_is_ok(cmd=submit_cmd, env=None, cwd=resource_path, logger=logger)
        cfn_type_details = get_last_cfn_type(type_name, region, is_third_party=False)
    if cfn_type_details is None:
        third_party = get_last_cfn_type(type_name, region, is_third_party=True, force_version=force_version)
        assert third_party, f"unable to find 3rd party type for {type_name}"
        last_updated = third_party.last_updated
        if confirm(
            f"No existing {type_name} found, ok to activate 3rd party: :\n'{third_party.version} ({humanize.naturalday(last_updated), {last_updated.isoformat()}})'\n?",
            is_interactive=is_interactive,
            default=True,
        ):
            activate_resource_type(third_party, region, cfn_execution_role)
            cfn_type_details = third_party
    assert cfn_type_details, f"no cfn_type_details found for {type_name}"
    # TODO: validate the active type details uses the execution role
