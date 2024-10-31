from __future__ import annotations
from typing import List, Optional, Union
from pydantic import BaseModel, ConfigDict, Field
from enum import Enum, StrEnum

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
    imports: List[str]

SnakeCaseString = str

class ComputedOptionalRequired(StrEnum):
    computed = "computed"
    computed_optional = "computed_optional"
    optional = "optional"
    required = "required"
    unset = ""

class BoolAttribute(BaseModelLocal):
    default: Optional[bool] = None

class Float64Attribute(BaseModelLocal):
    default: Optional[float] = None

class Int64Attribute(BaseModelLocal):
    default: Optional[int] = None

class MapAttribute(BaseModelLocal):
    default: Optional[CustomDefault] = None
    element_type: ElemType

class NestedAttributeObject(BaseModelLocal):
    attributes: List[Attribute]

class MapNestedAttribute(BaseModelLocal):
    default: Optional[CustomDefault] = None
    nested_object: NestedAttributeObject

class NumberAttribute(BaseModelLocal):
    default: Optional[CustomDefault] = None

class SetAttribute(BaseModelLocal):
    default: Optional[CustomDefault] = None
    element_type: ElemType

class SetNestedAttribute(BaseModelLocal):
    default: Optional[CustomDefault] = None
    nested_object: NestedAttributeObject

class SingleNestedAttribute(BaseModelLocal):
    default: Optional[CustomDefault] = None
    nested_object: NestedAttributeObject

class StringAttribute(BaseModelLocal):
    default: Optional[str] = None

class ListAttribute(BaseModelLocal):
    default: Optional[CustomDefault] = None
    element_type: ElemType

class ListNestedAttribute(BaseModelLocal):
    default: Optional[CustomDefault] = None
    nested_object: NestedAttributeObject

class Operation(int, Enum):
    CREATE = 0
    UPDATE = 1
    READ = 2
    DELETE = 3

class TimeoutsAttribute(BaseModelLocal):
    configurable_timeouts: List[Operation] = Field(default_factory=list, alias="configurabletimeouts")

class Attribute(BaseModelLocal):
    list: Optional[ListAttribute] = None
    float64: Optional[Float64Attribute] = None
    string: Optional[StringAttribute] = None
    bool: Optional[BoolAttribute] = None
    map: Optional[MapAttribute] = None
    number: Optional[NumberAttribute] = None
    set: Optional[SetAttribute] = None
    int64: Optional[Int64Attribute] = None
    
    set_nested: Optional[SetNestedAttribute] = None
    list_nested: Optional[ListNestedAttribute] = None
    map_nested: Optional[MapNestedAttribute] = None
    single_nested: Optional[SingleNestedAttribute] = None
    
    timeouts: Optional[TimeoutsAttribute] = None
    description: Optional[str] = None
    name: SnakeCaseString
    deprecation_message: Optional[str] = None
    sensitive: Optional[bool] = None
    
    computed_optional_required: Optional[ComputedOptionalRequired] = Field(default=None, alias="computedoptionalrequired")

    @property
    def is_nested(self) -> bool:
        return any([self.single_nested, self.list_nested, self.map_nested, self.set_nested])

    @property
    def is_attribute(self) -> bool:
        return self.computed_optional_required != ComputedOptionalRequired.unset

class Schema(BaseModelLocal):
    description: Optional[str] = None
    deprecation_message: Optional[str] = None
    attributes: List[Attribute]

class Resource(BaseModelLocal):
    schema: Schema
    name: SnakeCaseString

ResourceSchemaV3 = Resource