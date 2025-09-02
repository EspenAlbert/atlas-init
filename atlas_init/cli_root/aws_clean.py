import logging
from datetime import datetime, timedelta
from pathlib import Path

import humanize
import typer
from ask_shell import run_and_wait
from boto3.session import Session
from model_lib import Entity
from mypy_boto3_iam import IAMClient
from mypy_boto3_iam.type_defs import RoleTypeDef
from zero_3rdparty.datetime_utils import utc_now

from atlas_init.cloud.aws import PascalAlias
from atlas_init.settings.env_vars import init_settings
from atlas_init.typer_app import app_command

logger = logging.getLogger(__name__)


class LastUsed(Entity):
    model_config = PascalAlias
    last_used_date: datetime


class IAMRole(Entity):
    model_config = PascalAlias
    arn: str
    role_name: str
    create_date: datetime
    role_last_used: LastUsed | None = None


@app_command()
def aws_clean(
    skip_iam_roles: bool = typer.Option(False, help="skip iam roles"),
    iam_role_prefix_name: str = typer.Option(
        "mongodb-atlas-test-acc-tf-",
        help="prefix name of iam roles to clean",
    ),
):
    init_settings()
    if skip_iam_roles:
        return
    client: IAMClient = Session().client("iam")  # pyright: ignore[reportAssignmentType]
    all_roles: list[RoleTypeDef] = []
    aws_account_id = run_and_wait("aws sts get-caller-identity --query Account --output text").stdout_one_line

    roles_response = client.list_roles()

    all_roles.extend(roles_response["Roles"])
    marker = roles_response.get("Marker", "")
    while marker:
        roles_response = client.list_roles(Marker=marker)
        all_roles.extend(roles_response["Roles"])
        marker = roles_response.get("Marker", "")
    total_roles = len(all_roles)
    logger.info(f"found {total_roles} roles")
    roles_parsed: list[IAMRole] = []
    delete_if_created_before = utc_now() - timedelta(days=5)
    delete_count = 0
    role_names: list[str] = []
    for role in all_roles:
        parsed = IAMRole.model_validate(role)
        roles_parsed.append(parsed)
        role_name = parsed.role_name
        role_names.append(role_name)
        if not role_name.startswith(iam_role_prefix_name):
            continue
        # want to delte 'mongodb-atlas-test-acc-tf-1345851232260229574'
        # want to keep  'mongodb-atlas-test-acc-tf-7973337217371171538-git-ear'?
        if role_name[-1].isdigit() and parsed.create_date < delete_if_created_before:
            logger.info(f"role: {parsed.arn} will be deleted")
            delete_count += 1
            delete_role(client, role_name)
        else:
            logger.info(f"skipping role: {parsed.arn}, created: {humanize.naturaltime(parsed.create_date)}")
    logger.info(f"deleted {delete_count}/{total_roles} roles")
    out_path = Path(f"aws_roles_{aws_account_id}.txt")
    out_path.write_text("\n".join(sorted(role_names)))


def delete_role(client: IAMClient, role_name: str):
    try:
        attached_policies = client.list_attached_role_policies(RoleName=role_name)
        for policy in attached_policies["AttachedPolicies"]:
            policy_arn = policy.get("PolicyArn")
            if policy_arn:
                logger.info(f"detaching managed policy: {policy_arn} from role: {role_name}")
                client.detach_role_policy(RoleName=role_name, PolicyArn=policy_arn)
    except Exception as e:
        logger.warning(f"failed to detach managed policies from role {role_name}: {e}")

    # Second, delete all inline policies
    try:
        inline_policies = client.list_role_policies(RoleName=role_name)
        for policy_name in inline_policies["PolicyNames"]:
            logger.info(f"deleting inline policy: {policy_name} from role: {role_name}")
            client.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
    except Exception as e:
        logger.warning(f"failed to delete inline policies from role {role_name}: {e}")

    # Finally, delete the role
    try:
        client.delete_role(RoleName=role_name)
        logger.info(f"deleted role: {role_name}")
    except Exception as e:
        logger.error(f"failed to delete role {role_name}: {e}")
