import logging
from collections.abc import Iterable
from functools import singledispatch
from pathlib import Path
from typing import Literal

import pydantic
import requests
from model_lib import Entity, dump, field_names, parse_model
from zero_3rdparty import dict_nested
from zero_3rdparty.enum_utils import StrEnum

logger = logging.getLogger(__name__)


class ProviderSpecMapAttribute(Entity):
    computed_optional_required: Literal["computed_optional"]
    element_type: dict[str, dict]
    description: str


class ProviderSpecAttribute(Entity):
    name: str
    map: ProviderSpecMapAttribute | None = None

    def dump_provider_code_spec(self) -> dict:
        return self.model_dump(exclude_none=True)


class IgnoreNested(Entity):
    type: Literal["ignore_nested"] = "ignore_nested"
    path: str

    @property
    def use_wildcard(self) -> bool:
        return "*" in self.path


class RenameAttribute(Entity):
    type: Literal["rename_attribute"] = "rename_attribute"
    from_name: str
    to_name: str


class ComputedOptionalRequired(StrEnum):
    COMPUTED_OPTIONAL = "computed_optional"
    REQUIRED = "required"
    COMPUTED = "computed"
    OPTIONAL = "optional"


class ChangeAttributeType(Entity):
    type: Literal["change_attribute_type"] = "change_attribute_type"
    path: str
    new_value: ComputedOptionalRequired

    @classmethod
    def read_value(cls, attribute_dict: dict) -> str:
        return attribute_dict["string"]["computed_optional_required"]

    def update_value(self, attribute_dict: dict) -> None:
        attribute_dict["string"]["computed_optional_required"] = self.new_value


class TFResource(Entity):
    model_config = pydantic.ConfigDict(extra="allow")
    name: str
    extensions: list[IgnoreNested | RenameAttribute | ChangeAttributeType] = pydantic.Field(
        default_factory=list, discriminator="type"
    )
    provider_spec_attributes: list[ProviderSpecAttribute] = pydantic.Field(default_factory=list)

    def dump_generator_config(self) -> dict:
        names = field_names(self)
        return self.model_dump(exclude=set(names))


class PyTerraformSchema(Entity):
    resources: list[TFResource]
    data_sources: list[TFResource] = pydantic.Field(default_factory=list)

    def resource(self, resource: str) -> TFResource:
        return next(r for r in self.resources if r.name == resource)


def parse_py_terraform_schema(path: Path) -> PyTerraformSchema:
    return parse_model(path, PyTerraformSchema)


def dump_generator_config(schema: PyTerraformSchema) -> str:
    resources = {}
    for resource in schema.resources:
        resources[resource.name] = resource.dump_generator_config()
    data_sources = {ds.name: ds.dump_generator_config() for ds in schema.data_sources}
    generator_config = {
        "provider": {"name": "mongodbatlas"},
        "resources": resources,
        "data_sources": data_sources,
    }
    return dump(generator_config, "yaml")


class ProviderCodeSpec(Entity):
    model_config = pydantic.ConfigDict(extra="allow")
    provider: dict
    resources: list[dict]
    datasources: list[dict] = pydantic.Field(default_factory=list)
    version: str

    def resource_attributes(self, name: str) -> list:
        for r in self.resources:
            if r["name"] == name:
                return r["schema"]["attributes"]
        raise ValueError(f"resource: {name} not found!")

    def resource_attribute_names(self, name: str) -> list[str]:
        return [a["name"] for a in self.resource_attributes(name)]

    def iter_nested_attributes(self, name: str) -> Iterable[tuple[str, dict]]:
        for i, attribute in enumerate(self.resource_attributes(name)):
            for path, attr_dict in dict_nested.iter_nested_key_values(
                attribute, type_filter=dict, include_list_indexes=True
            ):
                yield f"[{i}].{path}", attr_dict

    def remove_nested_attribute(self, resource_name: str, path: str):
        logger.info(f"will remove attribute from {resource_name} with path: {path}")
        resource = next(r for r in self.resources if r["name"] == resource_name)
        full_path = f"schema.attributes.{path}"
        popped = dict_nested.pop_nested(resource, full_path, "")
        if popped == "":
            raise ValueError(f"failed to remove attribute from resource {resource_name} with path: {full_path}")
        assert isinstance(popped, dict), f"expected removed attribute to be a dict, got: {popped}"
        logger.info(f"removal ok, attribute_name: '{popped.get('name')}'")

    def read_attribute(self, resource_name: str, path: str) -> dict:
        if "." not in path:
            attribute_dict = next((a for a in self.resource_attributes(resource_name) if a["name"] == path), None)
        else:
            resource = next(r for r in self.resources if r["name"] == resource_name)
            attribute_dict = dict_nested.read_nested_or_none(resource, f"schema.attributes.{path}")
        if attribute_dict is None:
            raise ValueError(f"attribute {path} not found in resource {resource_name}")
        assert isinstance(
            attribute_dict, dict
        ), f"expected attribute to be a dict, got: {attribute_dict} @ {path} for resource={resource_name}"
        return attribute_dict


def update_provider_code_spec(schema: PyTerraformSchema, provider_code_spec_path: Path) -> str:
    spec = parse_model(provider_code_spec_path, t=ProviderCodeSpec)
    for resource in schema.resources:
        resource_name = resource.name
        if extra_spec_attributes := resource.provider_spec_attributes:
            add_explicit_attributes(spec, resource_name, extra_spec_attributes)
        for extension in resource.extensions:
            apply_extension(extension, spec, resource_name)
    return dump(spec, "json")


def add_explicit_attributes(spec, resource_name, extra_spec_attributes):
    resource_attributes = spec.resource_attributes(resource_name)
    existing_names = spec.resource_attribute_names(resource_name)
    new_names = [extra.name for extra in extra_spec_attributes]
    if both := set(existing_names) & set(new_names):
        raise ValueError(f"resource: {resource_name}, has already: {both} attributes")
    resource_attributes.extend(extra.dump_provider_code_spec() for extra in extra_spec_attributes)


@singledispatch
def apply_extension(extension: object, spec: ProviderCodeSpec, resource_name: str):  # noqa: ARG001
    raise NotImplementedError(f"unsupported extension: {extension!r}")


@apply_extension.register  # type: ignore
def _ignore_nested(extension: IgnoreNested, spec: ProviderCodeSpec, resource_name: str):
    if extension.use_wildcard:
        name_to_remove = extension.path.removeprefix("*.")
        assert "*" not in name_to_remove, f"only prefix *. is allowed for wildcard in path {extension.path}"
        found_paths = [
            path
            for path, attribute_dict in spec.iter_nested_attributes(resource_name)
            if attribute_dict.get("name", "") == name_to_remove
        ]
        while found_paths:
            next_to_remove = found_paths.pop()
            spec.remove_nested_attribute(resource_name, next_to_remove)
            found_paths = [
                path
                for path, attribute_dict in spec.iter_nested_attributes(resource_name)
                if attribute_dict.get("name", "") == name_to_remove
            ]
    else:
        err_msg = "only wildcard path is supported"
        raise NotImplementedError(err_msg)


@apply_extension.register  # type: ignore
def _rename_attribute(extension: RenameAttribute, spec: ProviderCodeSpec, resource_name: str):
    for attribute_dict in spec.resource_attributes(resource_name):
        if attribute_dict.get("name") == extension.from_name:
            logger.info(f"renaming attribute for {resource_name}: {extension.from_name} -> {extension.to_name}")
            attribute_dict["name"] = extension.to_name


@apply_extension.register  # type: ignore
def _change_attribute_type(extension: ChangeAttributeType, spec: ProviderCodeSpec, resource_name: str):
    attribute_dict = spec.read_attribute(resource_name, extension.path)
    old_value = extension.read_value(attribute_dict)
    if old_value == extension.new_value:
        logger.info(f"no change for {resource_name}: {extension.path} -> {extension.new_value}")
        return

    logger.info(f"changing attribute type for '{resource_name}.{extension.path}': {old_value} -> {extension.new_value}")
    extension.update_value(attribute_dict)


# reusing url from terraform-provider-mongodbatlas/scripts/schema-scaffold.sh
ADMIN_API_URL = "https://raw.githubusercontent.com/mongodb/atlas-sdk-go/main/openapi/atlas-api-transformed.yaml"


def admin_api_url(branch: str) -> str:
    return ADMIN_API_URL.replace("/main/", f"/{branch}/")


def download_admin_api(dest: Path, branch: str = "main") -> None:
    url = admin_api_url(branch)
    logger.info(f"downloading admin api to {dest} from {url}")
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    dest.write_bytes(response.content)
