from __future__ import annotations

from enum import Enum, StrEnum
from typing import TypeAlias

from pydantic import BaseModel, ConfigDict, Field


def lowercase_no_snake(name: str) -> str:
    return name.lower().replace("_", "")


def default_config_dict() -> ConfigDict:
    return ConfigDict(populate_by_name=True, alias_generator=lowercase_no_snake)


class BaseModelLocal(BaseModel):
    model_config = default_config_dict()


class ElemType(int, Enum):
    BOOL = 0
    FLOAT64 = 1
    INT64 = 2
    NUMBER = 3
    STRING = 4
    UNKNOWN = 5


class CustomDefault(BaseModelLocal):
    definition: str
    imports: list[str]


SnakeCaseString = str


class ComputedOptionalRequired(StrEnum):
    computed = "computed"
    computed_optional = "computed_optional"
    optional = "optional"
    required = "required"
    unset = ""


class BoolAttribute(BaseModelLocal):
    default: bool | None = None


class Float64Attribute(BaseModelLocal):
    default: float | None = None


class Int64Attribute(BaseModelLocal):
    default: int | None = None


class MapAttribute(BaseModelLocal):
    default: CustomDefault | None = None
    element_type: ElemType


class NestedAttributeObject(BaseModelLocal):
    attributes: list[Attribute]


class MapNestedAttribute(BaseModelLocal):
    default: CustomDefault | None = None
    nested_object: NestedAttributeObject


class NumberAttribute(BaseModelLocal):
    default: CustomDefault | None = None


class SetAttribute(BaseModelLocal):
    default: CustomDefault | None = None
    element_type: ElemType


class SetNestedAttribute(BaseModelLocal):
    default: CustomDefault | None = None
    nested_object: NestedAttributeObject


class SingleNestedAttribute(BaseModelLocal):
    default: CustomDefault | None = None
    nested_object: NestedAttributeObject


class StringAttribute(BaseModelLocal):
    default: str | None = None


class ListAttribute(BaseModelLocal):
    default: CustomDefault | None = None
    element_type: ElemType


class ListNestedAttribute(BaseModelLocal):
    default: CustomDefault | None = None
    nested_object: NestedAttributeObject


class Operation(int, Enum):
    CREATE = 0
    UPDATE = 1
    READ = 2
    DELETE = 3


class TimeoutsAttribute(BaseModelLocal):
    configurable_timeouts: list[Operation] = Field(default_factory=list, alias="configurabletimeouts")


NestedModelT: TypeAlias = SetNestedAttribute | ListNestedAttribute | MapNestedAttribute | SingleNestedAttribute


class Attribute(BaseModelLocal):
    list: ListAttribute | None = None
    float64: Float64Attribute | None = None
    string: StringAttribute | None = None
    bool: BoolAttribute | None = None
    map: MapAttribute | None = None
    number: NumberAttribute | None = None
    set: SetAttribute | None = None
    int64: Int64Attribute | None = None

    set_nested: SetNestedAttribute | None = None
    list_nested: ListNestedAttribute | None = None
    map_nested: MapNestedAttribute | None = None
    single_nested: SingleNestedAttribute | None = None

    timeouts: TimeoutsAttribute | None = None
    description: str | None = None
    name: SnakeCaseString
    deprecation_message: str | None = None
    sensitive: bool = False

    computed_optional_required: ComputedOptionalRequired | None = Field(default=None, alias="computedoptionalrequired")

    @property
    def is_nested(self) -> bool:
        return any([self.single_nested, self.list_nested, self.map_nested, self.set_nested])

    @property
    def nested_model(self) -> NestedModelT:
        assert self.is_nested
        return self.single_nested or self.list_nested or self.map_nested or self.set_nested  # type: ignore

    @property
    def is_attribute(self) -> bool:
        return self.computed_optional_required != ComputedOptionalRequired.unset

    @property
    def nested_attributes(self) -> list[Attribute]:
        return self.nested_model.nested_object.attributes


class Schema(BaseModelLocal):
    description: str | None = None
    deprecation_message: str | None = None
    attributes: list[Attribute]


class Resource(BaseModelLocal):
    schema: Schema
    name: SnakeCaseString


ResourceSchemaV3 = Resource
