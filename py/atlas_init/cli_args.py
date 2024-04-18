from typing import TypeAlias
from model_lib import Event
from pydantic import constr

SdkVersion: TypeAlias = constr(pattern="v\d{11}")
SDK_VERSION_HELP = "e.g., v20231115008 in go.mongodb.org/atlas-sdk/XXXX/admin"

class SdkVersionUpgrade(Event):
    old: SdkVersion
    new: SdkVersion
