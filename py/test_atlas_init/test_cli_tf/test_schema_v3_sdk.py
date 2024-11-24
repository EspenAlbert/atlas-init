import logging
from atlas_init.cli_tf.schema_go_parser import parse_schema_functions
from atlas_init.cli_tf.schema_table import explode_attributes
from atlas_init.cli_tf.schema_table_models import TFSchemaAttribute
from atlas_init.cli_tf.schema_v3 import Attribute, ComputedOptionalRequired, Resource
from atlas_init.cli_tf.schema_v3_sdk_base import (
    schema_attributes,
    set_allowed_missing_attributes,
    set_name_attribute_overrides,
)
from atlas_init.cli_tf.schema_v3_sdk_create import generate_schema_to_model
import pytest

from atlas_init.cli_tf.schema_v2_sdk import parse_sdk_model
from atlas_init.cli_tf.schema_v3_sdk import generate_model_go

logger = logging.getLogger(__name__)

adv_cluster_attr_overrides = {
    "ProjectId": "ProjectID",
    "Id": "ClusterID",
    "MongoDbEmployeeAccessGrant": "MongoDBEmployeeAccessGrant",
    "MongoDbMajorVersion": "MongoDBMajorVersion",
    "MongoDbVersion": "MongoDBVersion",
}


@pytest.mark.parametrize(
    "resource_name,sdk_model,attr_name_overrides,allowed_missing_attributes",
    [
        ("resourcepolicy", "ApiAtlasResourcePolicy", {}, set()),
        (
            "advancedcluster",
            "ClusterDescription20240805",
            adv_cluster_attr_overrides,
            {"mongo_db_employee_access_grant"},
        ),
        (
            "advancedclusterprocessargs",
            "ClusterDescriptionProcessArgs20240805",
            {},
            set(),
        ),
    ],
)
def test_model_go(
    sdk_repo_path,
    parse_resource_v3,
    resource_name,
    file_regression,
    sdk_model,
    attr_name_overrides,
    allowed_missing_attributes,
):
    set_name_attribute_overrides(attr_name_overrides)
    set_allowed_missing_attributes(allowed_missing_attributes)
    resource = parse_resource_v3(resource_name)
    parsed_sdk_model = parse_sdk_model(sdk_repo_path, sdk_model)
    actual = generate_model_go(resource, parsed_sdk_model)
    file_regression.check(actual, basename=f"model_from_{sdk_model}", extension=".go")


class _AttributeMissing(Exception):
    pass


def lookup_attribute_path(root: Resource | Attribute, path: str) -> Attribute:
    attributes = schema_attributes(root)
    err_msg = f"could not find attribute: {path} @ {root.name}"
    if "." not in path:
        try:
            return next(attr for attr in attributes if attr.name == path)
        except StopIteration:
            raise _AttributeMissing(err_msg) from None
    first, *rest = path.split(".")
    for attr in attributes:
        if attr.name == first:
            return lookup_attribute_path(attr, ".".join(rest))
    raise _AttributeMissing(err_msg)


def update_compuatbility(resource: Resource, live_attributes: list[TFSchemaAttribute]):
    for live_attr in live_attributes:
        path = live_attr.absolute_attribute_path
        try:
            attribute = lookup_attribute_path(resource, path)
        except _AttributeMissing as e:
            logger.warning(str(e))
            continue
        expected = live_attr.computability
        if attribute.computed_optional_required != expected:
            logger.warning(
                f"updating {path} Computability from {attribute.computed_optional_required} to {expected}"
            )
            attribute.computed_optional_required = expected


@pytest.mark.parametrize(
    "resource_name,sdk_model,attr_name_overrides",
    [
        # ("resourcepolicy", "ApiAtlasResourcePolicy", {}),
        ("advancedcluster", "ClusterDescription20240805", adv_cluster_attr_overrides),
        ("advancedclusterprocessargs", "ClusterDescriptionProcessArgs20240805", {}),
    ],
)
def test_schema_to_sdk(
    sdk_repo_path,
    parse_resource_v3,
    go_schema_paths,
    resource_name,
    file_regression,
    sdk_model,
    attr_name_overrides,
):
    set_name_attribute_overrides(attr_name_overrides)
    resource = parse_resource_v3(resource_name)
    tpf_path = go_schema_paths()["TPF"]
    live_attributes, _ = parse_schema_functions(tpf_path.read_text())
    live_attributes = explode_attributes(live_attributes)
    update_compuatbility(resource, live_attributes)

    parsed_sdk_model = parse_sdk_model(sdk_repo_path, sdk_model)
    actual = generate_schema_to_model(resource, parsed_sdk_model)
    file_regression.check(actual, basename=f"model_to_{sdk_model}", extension=".go")
