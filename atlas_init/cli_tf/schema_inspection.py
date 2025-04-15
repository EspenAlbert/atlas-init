import logging
import re
from collections.abc import Iterable
from pathlib import Path

from model_lib import Event

logger = logging.getLogger(__name__)


def log_optional_only(repo_path: Path):
    for resource_path in (repo_path / "internal").rglob("resource_*.go"):
        for name in schema_attributes_plugin_framework(resource_path, optional=True, computed=False):
            logger.info(f"found optional-only attr={name} in {resource_path}")


def schema_attributes_plugin_framework(path: Path, *, optional: bool = False, computed: bool = False) -> Iterable[str]:
    text = path.read_text()
    if "github.com/hashicorp/terraform-plugin-framework/resource/schema" not in text:
        return
    for attr in iterate_schema_attributes(text, "MapAttribute", "ListAttribute"):
        if attr.optional == optional and attr.computed == computed:
            yield attr.name


class SchemaAttr(Event):
    name: str
    optional: bool = False
    computed: bool = False
    attribute_type: str


def as_regex(attribute_type: str) -> re.Pattern:
    return re.compile(
        rf'"(?P<name>[\w_]+)": (?P<attribute_type>schema\.{attribute_type})\{{(?P<brackets>[^}}]+)\}}',
        re.MULTILINE,
    )


def unpack_flags(brackets: str) -> dict[str, bool]:
    return {
        "optional": "Optional:" in brackets,
        "computed": "Computed:" in brackets,
    }


def iterate_schema_attributes(text: str, *attribute_types: str) -> Iterable[SchemaAttr]:
    for attr_type in attribute_types:
        pattern = as_regex(attr_type)
        m: re.Match
        for m in pattern.finditer(text):
            match_dict = m.groupdict()
            flags = unpack_flags(match_dict.pop("brackets"))
            yield SchemaAttr(**match_dict, **flags)  # type: ignore
