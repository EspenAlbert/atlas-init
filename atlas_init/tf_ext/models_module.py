from dataclasses import dataclass, Field, fields
from types import ModuleType
from abc import ABC
from typing import ClassVar
from zero_3rdparty.object_name import as_name

from atlas_init.tf_ext.py_gen import make_post_init_line_from_field


@dataclass
class ResourceAbs(ABC):
    REQUIRED_ATTRIBUTES: ClassVar[set[str]] = set()
    NESTED_ATTRIBUTES: ClassVar[set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES: ClassVar[set[str]] = set()
    COMPUTED_ONLY_ATTRIBUTES_NAME: ClassVar[str] = "COMPUTED_ONLY_ATTRIBUTES"


def as_import_line(name: str) -> str:
    from_part, name_part = name.rsplit(".", maxsplit=1)
    return f"from {from_part} import {name_part}"


@dataclass
class ResourceTypePythonModule:
    resource_type: str
    resource: type[ResourceAbs] | None = None
    resource_ext: type[ResourceAbs] | None = None
    module: ModuleType | None = None

    @property
    def resource_ext_cls_used(self) -> bool:
        return self.resource_ext is not None

    @property
    def errors_func_used(self) -> bool:
        return self.module is not None and getattr(self.module, "errors", None) is not None

    @property
    def modify_out_func_used(self) -> bool:
        return self.module is not None and hasattr(self.module, "modify_out")

    @property
    def extra_post_init_lines(self) -> list[str]:
        if self.resource_ext is None:
            return []
        return [make_post_init_line_from_field(extra_field) for extra_field in self.extra_fields]

    @property
    def base_fields(self) -> list[Field]:
        if self.resource is None:
            return []
        return list(fields(self.resource))

    @property
    def base_field_names(self) -> list[str]:
        return sorted(f.name for f in self.base_fields)

    @property
    def base_field_names_not_computed(self) -> list[str]:
        computed = getattr(self.resource, ResourceAbs.COMPUTED_ONLY_ATTRIBUTES_NAME, set())
        return sorted(name for name in self.base_field_names if name not in computed)

    @property
    def extra_fields(self) -> list[Field]:
        if self.resource is None or self.resource_ext is None:
            return []
        base_fields = {f.name for f in self.base_fields}
        return sorted((f for f in fields(self.resource_ext) if f.name not in base_fields), key=lambda f: f.name)

    @property
    def extra_fields_names(self) -> list[str]:
        return [f.name for f in self.extra_fields]

    @property
    def extra_import_lines(self) -> list[str]:
        module = self.module
        if not module:
            return []
        return [
            as_import_line(as_name(value))
            for key, value in vars(module).items()
            if not key.startswith("_") and not as_name(value).startswith(("__", self.resource_type))
        ]
