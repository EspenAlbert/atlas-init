import contextlib
import logging
import re
from collections.abc import Iterable
from pathlib import Path

import stringcase
from model_lib import Entity, dump, parse_model
from pydantic import ConfigDict, Field, ValidationError

logger = logging.getLogger(__name__)


def create_sample_file(
    samples_file: Path,
    log_group_name: str,
    resource_state: dict,
    prev_resource_state: dict | None = None,
):
    logger.info(f"adding sample @ {samples_file}")
    assert isinstance(resource_state, dict)
    new_json = dump(
        {
            "providerLogGroupName": log_group_name,
            "previousResourceState": prev_resource_state or {},
            "desiredResourceState": resource_state,
        },
        "json",
    )
    samples_file.write_text(new_json)


CamelAlias = ConfigDict(alias_generator=stringcase.camelcase, populate_by_name=True)


class CfnSchema(Entity):
    model_config = CamelAlias

    description: str
    type_name: str = Field(pattern=r"^[a-zA-Z0-9]{2,64}::[a-zA-Z0-9]{2,64}::[a-zA-Z0-9]{2,64}$")


def iterate_schemas(resource_root: Path) -> Iterable[tuple[Path, CfnSchema]]:
    for path in resource_root.rglob("*.json"):
        if path.parent.parent != resource_root:
            continue
        with contextlib.suppress(ValidationError):
            yield path, parse_model(path, t=CfnSchema)


_md_patterns = [
    re.compile(r"\[[^\]]+\]\([^\)]+\)"),
    re.compile(r"`\S+`"),
]


def has_md_link(text: str) -> bool:
    return any(bool(pattern.findall(text)) for pattern in _md_patterns)
