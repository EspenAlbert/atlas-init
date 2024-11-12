from functools import singledispatch
from typing import NamedTuple

from atlas_init.cli_tf.schema_v2_sdk import SDKAttribute
from atlas_init.cli_tf.schema_v3 import Attribute, Resource
from atlas_init.humps import pascalize


class SDKAndSchemaAttribute(NamedTuple):
    sdk_attribute: SDKAttribute
    schema_attribute: Attribute


def find_attribute(attributes: list[Attribute], name: str, root_name: str) -> Attribute:
    for schema_attribute in attributes:
        if name == schema_attribute.name:
            return schema_attribute
    raise ValueError(f"could not find schema attribute for {name} on resource: {root_name}")


@singledispatch
def schema_attributes(root: object) -> list[Attribute]:
    raise NotImplementedError(f"unsupported root type: {type(root)} to find schema attributes")


@schema_attributes.register
def _resource_attributes(root: Resource) -> list[Attribute]:
    return root.schema.attributes


@schema_attributes.register
def _attribute_nested(root: Attribute) -> list[Attribute]:
    return root.nested_attributes


def name_schema_struct(name: str) -> str:
    return f"TF{pascalize(name)}Model"


def name_struct_attribute(name: str) -> str:
    default = pascalize(name)
    if override := _name_attribute_overrides.get(default):
        return override
    return default


_name_attribute_overrides = {}


def set_name_attribute_overrides(overrides: dict[str, str]):
    global _name_attribute_overrides  # noqa: PLW0603 `Using the global statement to update `_name_attribute_overrides` is discouraged`
    _name_attribute_overrides = overrides
