import logging
import re
from typing import Annotated, Literal

import typer
from model_lib import Entity
from pydantic import BeforeValidator, model_validator

logger = logging.getLogger(__name__)


type ChangelogGroup = Literal["rs", "ds", "dsp"]
CHANGELOG_GROUPS = {"rs", "ds", "dsp"}
_group_prefixes = {
    "rs": "resource/",
    "ds": "data-source/",
    "dsp": "data-source/",
}
_group_suffixes = {
    "rs": "",
    "ds": "",
    "dsp": "s",
}
type ChangelogType = Literal["feat", "fix"]
CHANGELOG_SEPARATOR = "\n\n"
_types_headers = {"feat": "enhancement", "fix": "bug"}
_line_regex = re.compile(r"(?P<type>feat|fix)\((?P<groups>[^\]]+)\)\:\s(?P<text>.*)")


def as_group_name(resource_name: str, group: ChangelogGroup):
    prefix = _group_prefixes[group]
    suffix = _group_suffixes[group]
    return f"{prefix}{resource_name}{suffix}"


def changelog_header(group: ChangelogType) -> str:
    return f"release-note:{_types_headers[group]}"


def split_on_plus(groups: str | list[str]) -> list[str]:
    return groups.split("+") if isinstance(groups, str) else groups


type GroupsValidation = Annotated[str, BeforeValidator(split_on_plus)]


class ChangelogPart(Entity):
    type: ChangelogType
    groups: str
    text: str
    resource_name: str

    @property
    def parsed_groups(self) -> list[ChangelogGroup]:
        groups = set(self.groups.split("+"))
        if invalid_groups := groups - CHANGELOG_GROUPS:
            raise ValueError(f"found invalid groups {invalid_groups}, only {CHANGELOG_GROUPS} are valid")
        return sorted(groups)  # type: ignore

    @model_validator(mode="after")
    def ensure_parsed_groups(self):
        assert self.parsed_groups
        return self

    def as_changelog(self) -> str:
        parts = []
        for group in self.parsed_groups:
            header = changelog_header(self.type)
            name = as_group_name(self.resource_name, group)
            parts.append(f"```{header}\n{name}: {self.text}\n```")
        return CHANGELOG_SEPARATOR.join(parts)

    def __str__(self) -> str:
        return self.as_changelog()


def _convert_to_changelog(changes: str) -> str:
    if not changes.startswith("rs="):
        err = "missing rs=YOUR_RESOURCE_NAME e.g., mongodbatlas_federated_settings_org_config"
        raise ValueError(err)
    header, *change_lines = changes.splitlines()
    rs = header.removeprefix("rs=").strip()
    changelog = []
    for change in change_lines:
        if changelog_part := as_changelog_parts(rs, change):
            changelog.append(changelog_part)
    logger.info(f"found a total of {len(changelog)} changes")
    return CHANGELOG_SEPARATOR.join(str(part) for part in changelog)


def as_changelog_parts(resource_name: str, line_raw: str) -> ChangelogPart | None:
    if match := _line_regex.search(line_raw):
        return ChangelogPart(**match.groupdict(), resource_name=resource_name)  # type: ignore
    logger.warning(f"unable to parse line: {line_raw}")
    return None


def convert_to_changelog(changes: str) -> str:
    try:
        return _convert_to_changelog(changes)
    except ValueError as e:
        logger.critical(str(e))
        raise typer.Abort from e
