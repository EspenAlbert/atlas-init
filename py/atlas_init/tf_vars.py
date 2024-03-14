from typing import Any
from atlas_init.config import ChangeGroup, TerraformVars
from atlas_init.env_vars import AtlasInitSettings


def get_tf_vars(settings: AtlasInitSettings, active_groups: list[ChangeGroup]) -> dict[str, Any]:
    tf_vars = sum((group.vars for group in active_groups), start=TerraformVars()) if len(active_groups) > 1 else active_groups[0].vars
    external_settings = settings.external_settings
    return {
        "aws_profile": external_settings.AWS_PROFILE,
        "atlas_public_key": external_settings.MONGODB_ATLAS_PUBLIC_KEY,
        "atlas_private_key": external_settings.MONGODB_ATLAS_PRIVATE_KEY,
        "org_id": external_settings.MONGODB_ATLAS_ORG_ID,
        "aws_region": external_settings.AWS_REGION,
        "aws_region_cfn_secret": external_settings.AWS_REGION,
        "project_name": settings.unique_name,
        "your_name_lower": settings.unique_name,
        "create_cfn_secret": settings.cfn_secret,
        "extra_env_vars": settings.manual_env_vars,
        **tf_vars.model_dump(),
    }
