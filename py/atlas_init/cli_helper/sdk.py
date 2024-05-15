import re
from collections.abc import Iterable
from pathlib import Path
from typing import Annotated, Literal, NamedTuple

import requests
from model_lib import Event
from pydantic import StringConstraints


class Change(NamedTuple):
    change_type: Literal["changed from", "removed"]
    class_name: str
    func_name: str


regex = re.compile(r"\-\s\(?\\?\*?(?P<class_name>\w+)\)?\.(?P<func_name>\w+):\s(?P<change_type>(removed|changed from))")


def parse_line(line: str) -> Change | None:
    if match := regex.match(line):
        # change = match.groupdict()["change"]
        # func_name = match.groupdict()["func_name"]
        return Change(**match.groupdict())  # type: ignore
    return None


class BreakingChange(NamedTuple):
    version: str
    line: str


def parse_breaking_changes(
    breaking_change_dir: Path,
    start_sdk_version: str = "v20231115000",
    end_sdk_version: str = "v20991115000",
) -> dict[Change, BreakingChange]:
    changes: dict[Change, BreakingChange] = {}
    for file in breaking_change_dir.glob("*.md"):
        # v20231115009.md
        sdk_version = file.name.removesuffix(".md")
        if sdk_version <= start_sdk_version or sdk_version > end_sdk_version:
            continue
        for line in file.read_text().splitlines():
            if change := parse_line(line):
                changes[change] = BreakingChange(sdk_version, line)
    return changes


def find_breaking_changes(text: str, changes: dict[Change, BreakingChange]) -> dict[Change, BreakingChange]:
    found_changes: dict[Change, BreakingChange] = {}
    for change, change_value in changes.items():
        if change.class_name in text and change.func_name in text:
            found_changes[change] = change_value
    return found_changes


def format_breaking_changes(text: str, changes: dict[Change, BreakingChange]):
    warning: list[str] = []
    for (_, cls_name, func_name), breaking_change in changes.items():
        warning.append(f"## {breaking_change.version}: {breaking_change.line}")
        for line_nr, line in enumerate(text.splitlines(), 1):
            if cls_name in line:
                warning.append(f"L{line_nr:03}: '{cls_name}' {line}")
            if func_name in line:
                warning.append(f"L{line_nr:03}: '{func_name}' {line}")
        warning.append("")
    return "\n".join(warning)


def is_removed(changes: Iterable[Change]) -> bool:
    return any(change.change_type == "removed" for change in changes)


def find_latest_sdk_version() -> str:
    response = requests.get("https://api.github.com/repos/mongodb/atlas-sdk-go/releases/latest", timeout=10)
    response.raise_for_status()
    name = response.json()["name"]
    assert isinstance(name, str)
    return name.removesuffix(".0.0")


SdkVersion = Annotated[str, StringConstraints(pattern="v\\d{11}")]


class SdkVersionUpgrade(Event):
    old: SdkVersion
    new: SdkVersion


SDK_VERSION_HELP = "e.g., v20231115008 in go.mongodb.org/atlas-sdk/XXXX/admin"
