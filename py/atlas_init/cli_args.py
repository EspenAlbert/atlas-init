from typing import TypeAlias
from model_lib import Entity, Event
from pydantic import constr, model_validator
from zero_3rdparty.str_utils import ensure_prefix

SdkVersion: TypeAlias = constr(pattern="v\d{11}") # type: ignore
SDK_VERSION_HELP = "e.g., v20231115008 in go.mongodb.org/atlas-sdk/XXXX/admin"

class SdkVersionUpgrade(Event):
    old: SdkVersion
    new: SdkVersion

class CfnType(Entity):
    type_name: str
    region_filter: str

    @model_validator(mode="after")
    def ensure_type_name_prefix(self):
        self.type_name = ensure_prefix(self.type_name, "MongoDB::Atlas::")
        return self
