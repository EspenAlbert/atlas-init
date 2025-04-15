import logging
from collections.abc import Iterable
from functools import singledispatch
from pathlib import Path
from typing import Annotated, Literal, NamedTuple

import pydantic
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


class SkipValidators(Entity):
    type: Literal["skip_validators"] = "skip_validators"


Extension = Annotated[
    IgnoreNested | RenameAttribute | ChangeAttributeType | SkipValidators,
    pydantic.Field("type"),
]


class TFResource(Entity):
    model_config = pydantic.ConfigDict(extra="allow")
    name: str
    extensions: list[Extension] = pydantic.Field(default_factory=list)
    provider_spec_attributes: list[ProviderSpecAttribute] = pydantic.Field(
        default_factory=list
    )

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


class AttributeTuple(NamedTuple):
    name: str
    path: str
    attribute_dict: dict

    @property
    def attribute_path(self) -> str:
        return f"{self.path}.{self.name}" if self.path else self.name


class ProviderCodeSpec(Entity):
    model_config = pydantic.ConfigDict(extra="allow")
    provider: dict
    resources: list[dict]
    datasources: list[dict] = pydantic.Field(default_factory=list)
    version: str

    def root_dict(self, name: str, is_datasource: bool = False) -> dict:  # noqa: FBT002
        resources = self.datasources if is_datasource else self.resources
        root_value = next((r for r in resources if r["name"] == name), None)
        if root_value is None:
            raise ValueError(f"{self.root_name(name, is_datasource)} not found!")
        return root_value

    def schema_attributes(
        self, name: str, is_datasource: bool = False
    ) -> list:
        root_dict = self.root_dict(name, is_datasource)
        return root_dict["schema"]["attributes"]

    def _type_name(self, is_datasource: bool):
        return "datasource" if is_datasource else "resource"

    def root_name(self, name: str, is_datasource: bool):
        return f"{self._type_name(is_datasource)}.{name}"

    def attribute_names(
        self, name: str, is_datasource: bool = False
    ) -> list[str]:
        return [
            a["name"] for a in self.schema_attributes(name, is_datasource=is_datasource)
        ]

    def iter_all_attributes(
        self, name: str, is_datasource: bool = False
    ) -> Iterable[AttributeTuple]:
        for attribute in self.schema_attributes(name=name, is_datasource=is_datasource):
            yield AttributeTuple(attribute["name"], "", attribute)
        yield from self.iter_nested_attributes(name, is_datasource=is_datasource)

    def iter_nested_attributes(
        self, name: str, is_datasource: bool = False
    ) -> Iterable[AttributeTuple]:
        for i, attribute in enumerate(
            self.schema_attributes(name=name, is_datasource=is_datasource)
        ):
            for path, attr_dict in dict_nested.iter_nested_key_values(
                attribute, type_filter=dict, include_list_indexes=True
            ):
                full_path = f"[{i}].{path}"
                if name := attr_dict.get("name", ""):
                    yield AttributeTuple(name, full_path, attr_dict)

    def remove_nested_attribute(
        self, name: str, path: str, is_datasource: bool = False
    ) -> None:
        root_name = self.root_name(name, is_datasource)
        logger.info(f"will remove attribute from {root_name} with path: {path}")
        root_attributes = self.root_dict(name, is_datasource)
        full_path = f"schema.attributes.{path}"
        popped = dict_nested.pop_nested(root_attributes, full_path, "")
        if popped == "":
            raise ValueError(
                f"failed to remove attribute from resource {name} with path: {full_path}"
            )
        assert isinstance(
            popped, dict
        ), f"expected removed attribute to be a dict, got: {popped}"
        logger.info(f"removal ok, attribute_name: '{root_name}.{popped.get('name')}'")

    def read_attribute(
        self, name: str, path: str, *, is_datasource: bool = False
    ) -> dict:
        if "." not in path:
            attribute_dict = next(
                (
                    a
                    for a in self.schema_attributes(name, is_datasource)
                    if a["name"] == path
                ),
                None,
            )
        else:
            root_dict = self.root_dict(name, is_datasource)
            attribute_dict = dict_nested.read_nested_or_none(
                root_dict, f"schema.attributes.{path}"
            )
        if attribute_dict is None:
            raise ValueError(
                f"attribute {path} not found in {self.root_name(name, is_datasource)}"
            )
        assert isinstance(
            attribute_dict, dict
        ), f"expected attribute to be a dict, got: {attribute_dict} @ {path} for resource={name}"
        return attribute_dict


def update_provider_code_spec(
    schema: PyTerraformSchema, provider_code_spec_path: Path
) -> str:
    spec = parse_model(provider_code_spec_path, t=ProviderCodeSpec)
    for resource in schema.resources:
        resource_name = resource.name
        if extra_spec_attributes := resource.provider_spec_attributes:
            add_explicit_attributes(spec, resource_name, extra_spec_attributes)
        for extension in resource.extensions:
            apply_extension(extension, spec, resource_name)
    for data_source in schema.data_sources:
        data_source_name = data_source.name
        if extra_spec_attributes := data_source.provider_spec_attributes:
            add_explicit_attributes(
                spec, data_source_name, extra_spec_attributes, is_datasource=True
            )
        for extension in data_source.extensions:
            apply_extension(extension, spec, data_source_name, is_datasource=True)
    return dump(spec, "json")


def add_explicit_attributes(
    spec: ProviderCodeSpec,
    name: str,
    extra_spec_attributes: list[ProviderSpecAttribute],
    *,
    is_datasource=False,
):
    resource_attributes = spec.schema_attributes(name, is_datasource=is_datasource)
    existing_names = spec.attribute_names(name, is_datasource=is_datasource)
    new_names = [extra.name for extra in extra_spec_attributes]
    if both := set(existing_names) & set(new_names):
        raise ValueError(f"resource: {name}, has already: {both} attributes")
    resource_attributes.extend(
        extra.dump_provider_code_spec() for extra in extra_spec_attributes
    )


@singledispatch
def apply_extension(
    extension: object,
    spec: ProviderCodeSpec,
    resource_name: str,
    *,
    is_datasource: bool = False,
):
    raise NotImplementedError(f"unsupported extension: {extension!r}")


@apply_extension.register  # type: ignore
def _ignore_nested(
    extension: IgnoreNested,
    spec: ProviderCodeSpec,
    resource_name: str,
    *,
    is_datasource: bool = False,
):
    if extension.use_wildcard:
        name_to_remove = extension.path.removeprefix("*.")
        assert (
            "*" not in name_to_remove
        ), f"only prefix *. is allowed for wildcard in path {extension.path}"
        found_paths = [
            path
            for name, path, attribute_dict in spec.iter_nested_attributes(
                resource_name, is_datasource=is_datasource
            )
            if name == name_to_remove
        ]
        while found_paths:
            next_to_remove = found_paths.pop()
            spec.remove_nested_attribute(
                resource_name, next_to_remove, is_datasource=is_datasource
            )
            found_paths = [
                path
                for name, path, attribute_dict in spec.iter_nested_attributes(
                    resource_name, is_datasource=is_datasource
                )
                if name == name_to_remove
            ]
    else:
        err_msg = "only wildcard path is supported"
        raise NotImplementedError(err_msg)


@apply_extension.register  # type: ignore
def _rename_attribute(
    extension: RenameAttribute,
    spec: ProviderCodeSpec,
    resource_name: str,
    *,
    is_datasource: bool = False,
):
    for attribute_dict in spec.schema_attributes(
        resource_name, is_datasource=is_datasource
    ):
        if attribute_dict.get("name") == extension.from_name:
            logger.info(
                f"renaming attribute for {spec.root_name(resource_name, is_datasource)}: {extension.from_name} -> {extension.to_name}"
            )
            attribute_dict["name"] = extension.to_name


@apply_extension.register  # type: ignore
def _change_attribute_type(
    extension: ChangeAttributeType,
    spec: ProviderCodeSpec,
    resource_name: str,
    *,
    is_datasource: bool = False,
):
    attribute_dict = spec.read_attribute(
        resource_name, extension.path, is_datasource=is_datasource
    )
    old_value = extension.read_value(attribute_dict)
    if old_value == extension.new_value:
        logger.info(
            f"no change for '{spec.root_name(resource_name, is_datasource)}': {extension.path} -> {extension.new_value}"
        )
        return

    logger.info(
        f"changing attribute type for '{spec.root_name(resource_name, is_datasource)}.{extension.path}': {old_value} -> {extension.new_value}"
    )
    extension.update_value(attribute_dict)


@apply_extension.register  # type: ignore
def _skip_validators(
    _: SkipValidators,
    spec: ProviderCodeSpec,
    resource_name: str,
    *,
    is_datasource: bool = False,
):
    for attr_tuple in spec.iter_all_attributes(
        resource_name, is_datasource=is_datasource
    ):
        attribute_dict = attr_tuple.attribute_dict
        paths_to_pop = [
            f"{path}.validators"
            for path, nested_dict in dict_nested.iter_nested_key_values(
                attribute_dict, type_filter=dict
            )
            if "validators" in nested_dict
        ]
        if paths_to_pop:
            logger.info(f"popping validators from '{attr_tuple.attribute_path}'")
        for path in paths_to_pop:
            dict_nested.pop_nested(attribute_dict, path)
