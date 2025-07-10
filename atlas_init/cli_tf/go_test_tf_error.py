from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from functools import total_ordering
from typing import ClassVar, Literal, NamedTuple, Self, TypeAlias

import humanize
from model_lib import Entity, utc_datetime_ms
from pydantic import Field, model_validator
from zero_3rdparty import iter_utils
from zero_3rdparty.datetime_utils import utc_now
from zero_3rdparty.str_utils import instance_repr

from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.repos.go_sdk import ApiSpecPaths


class GoTestErrorClass(StrEnum):
    """Goal of each error class to be actionable."""

    FLAKY_400 = "flaky_400"
    FLAKY_500 = "flaky_500"
    FLAKY_CHECK = "flaky_check"
    FLAKY_CLIENT = "flaky_client"
    OUT_OF_CAPACITY = "out_of_capacity"
    PROJECT_LIMIT_EXCEEDED = "project_limit_exceeded"
    DANGLING_RESOURCE = "dangling_resource"
    REAL_TEST_FAILURE = "real_test_failure"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"
    PROVIDER_DOWNLOAD = "provider_download"
    UNCLASSIFIED = "unclassified"

    __ACTIONS__ = {
        FLAKY_400: "retry",
        FLAKY_500: "retry",
        FLAKY_CHECK: "retry",
        FLAKY_CLIENT: "retry",
        PROVIDER_DOWNLOAD: "retry",
        OUT_OF_CAPACITY: "retry_later",
        PROJECT_LIMIT_EXCEEDED: "clean_project",
        DANGLING_RESOURCE: "update_cleanup_script",
        REAL_TEST_FAILURE: "investigate",
        TIMEOUT: "investigate",
        UNKNOWN: "investigate",
    }
    __CONTAINS_MAPPING__ = {
        OUT_OF_CAPACITY: ("OUT_OF_CAPACITY",),
        FLAKY_500: ("HTTP 500", "UNEXPECTED_ERROR", "503 Service Unavailable"),
        FLAKY_CLIENT: ("dial tcp: lookup", "i/o timeout"),
        PROVIDER_DOWNLOAD: [
            "mongodbatlas: failed to retrieve authentication checksums for provider",
            "Error: Failed to install provider github.com: bad response",
        ],
        TIMEOUT: ("timeout while waiting for",),
    }

    @classmethod
    def auto_classification(cls, output: str) -> GoTestErrorClass | None:
        def contains(output: str, contains_part: str) -> bool:
            if " " in contains_part:
                return all(part in output for part in contains_part.split())
            return contains_part in output

        return next(
            (
                error_class
                for error_class, contains_list in cls.__CONTAINS_MAPPING__.items()
                if any(contains(output, contains_part) for contains_part in contains_list)
            ),
            None,
        )  # type: ignore


API_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]


class GoTestAPIError(Entity):
    type: Literal["api_error"] = "api_error"
    api_error_code_str: str
    api_path: str
    api_method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"]
    api_response_code: int
    tf_resource_name: str = ""
    tf_resource_type: str = ""
    step_nr: int = -1

    api_path_normalized: str = Field(init=False, default="")

    @model_validator(mode="after")
    def strip_path_chars(self) -> GoTestAPIError:
        self.api_path = self.api_path.rstrip(":/")
        return self

    def add_info_fields(self, info: DetailsInfo) -> None:
        if api_paths := info.paths:
            self.api_path_normalized = api_paths.normalize_path(self.api_method, self.api_path)

    def __str__(self) -> str:
        resource_part = f"{self.tf_resource_type} " if self.tf_resource_type else ""
        if self.api_path_normalized:
            return f"{resource_part}{self.api_error_code_str} {self.api_method} {self.api_path_normalized} {self.api_response_code}"
        return f"{resource_part}{self.api_error_code_str} {self.api_method} {self.api_path} {self.api_response_code}"


@total_ordering
class CheckError(Entity):
    attribute: str = ""
    expected: str = ""
    got: str = ""
    check_nr: int = -1

    def __lt__(self, other) -> bool:
        if not isinstance(other, CheckError):
            raise TypeError
        return (self.check_nr, self.attribute) < (other.check_nr, other.attribute)

    def __str__(self) -> str:
        if self.attribute and self.expected and self.got:
            return f"{self.check_nr}({self.attribute}:expected:{self.expected}, got: {self.got})"
        return f"{self.check_nr}"

    @classmethod
    def parse_from_output(cls, output: str) -> list[Self]:
        return [
            cls(**check_match.groupdict())  # type: ignore
            for check_match in check_pattern.finditer(output)
        ]


class GoTestResourceCheckError(Entity):
    type: Literal["check_error"] = "check_error"
    tf_resource_name: str
    tf_resource_type: str
    step_nr: int = -1
    check_errors: list[CheckError] = Field(default_factory=list)
    test_name: str = ""

    def add_info_fields(self, info: DetailsInfo) -> None:
        self.test_name = info.run.name

    def __str__(self) -> str:
        return f"{self.tf_resource_type} {self.tf_resource_name} {self.step_nr} {self.check_errors}"

    @property
    def check_numbers_str(self) -> str:
        return ",".join(str(check.check_nr) for check in sorted(self.check_errors))

    def check_errors_match(self, other_check_errors: list[CheckError]) -> bool:
        if len(self.check_errors) != len(other_check_errors):
            return False
        return all(
            any(
                check.check_nr == other_check.check_nr and check.attribute == other_check.attribute
                for other_check in other_check_errors
            )
            for check in self.check_errors
        )


class GoTestGeneralCheckError(Entity):
    type: Literal["general_check_error"] = "general_check_error"
    step_nr: int = -1
    check_errors: list[CheckError] = Field(default_factory=list)
    error_check_str: str
    test_name: str = ""

    def add_info_fields(self, info: DetailsInfo) -> None:
        self.test_name = info.run.name

    def check_errors_str(self) -> str:
        return ",".join(str(check) for check in sorted(self.check_errors))

    def __str__(self) -> str:
        return f"Step {self.step_nr} {self.check_errors_str()}"


@dataclass
class DetailsInfo:
    run: GoTestRun
    paths: ApiSpecPaths | None = None


class GoTestDefaultError(Entity):
    type: Literal["default_error"] = "default_error"
    error_str: str

    def add_info_fields(self, _: DetailsInfo) -> None:
        pass


ErrorDetailsT: TypeAlias = GoTestAPIError | GoTestResourceCheckError | GoTestDefaultError | GoTestGeneralCheckError


class ErrorClassified(NamedTuple):
    classified: dict[GoTestErrorClass, list[GoTestError]]
    unclassified: list[GoTestError]


class ErrorClassAuthor(StrEnum):
    AUTO = "auto"
    HUMAN = "human"
    LLM = "llm"
    SIMILAR = "similar"


class GoTestErrorClassification(Entity):
    error_class: GoTestErrorClass = GoTestErrorClass.UNCLASSIFIED
    ts: utc_datetime_ms = Field(default_factory=utc_now)
    author: ErrorClassAuthor
    confidence: float = 0.0
    test_output: str = ""
    details: ErrorDetailsT
    run_id: str
    test_name: str

    STR_COLUMNS: ClassVar[list[str]] = ["error_class", "author", "run_id", "confidence", "ts_when"]

    def needs_classification(self, confidence_threshold: float = 1.0) -> bool:
        return (
            self.error_class in {GoTestErrorClass.UNCLASSIFIED, GoTestErrorClass.UNKNOWN}
            or self.confidence < confidence_threshold
        )

    @property
    def ts_when(self) -> str:
        return humanize.naturaltime(self.ts)

    def __str__(self) -> str:
        return instance_repr(self, self.STR_COLUMNS)


@total_ordering
class GoTestError(Entity):
    details: ErrorDetailsT
    run: GoTestRun
    bot_error_class: GoTestErrorClass = GoTestErrorClass.UNCLASSIFIED
    human_error_class: GoTestErrorClass = GoTestErrorClass.UNCLASSIFIED

    def __lt__(self, other) -> bool:
        if not isinstance(other, GoTestError):
            raise TypeError
        return self.run < other.run

    @property
    def run_id(self) -> str:
        return self.run.id

    @property
    def run_name(self) -> str:
        return self.run.name

    @property
    def classifications(self) -> tuple[GoTestErrorClass, GoTestErrorClass] | None:
        if (
            self.bot_error_class != GoTestErrorClass.UNCLASSIFIED
            and self.human_error_class != GoTestErrorClass.UNCLASSIFIED
        ):
            return self.bot_error_class, self.human_error_class
        return None

    def set_human_and_bot_classification(self, chosen_class: GoTestErrorClass) -> None:
        self.human_error_class = chosen_class
        self.bot_error_class = chosen_class

    def match(self, other: GoTestError) -> bool:
        if self.run.id == other.run.id:
            return True
        details = self.details
        other_details = other.details
        if type(self.details) is not type(other_details):
            return False
        if isinstance(details, GoTestAPIError):
            assert isinstance(other_details, GoTestAPIError)
            return (
                details.api_path_normalized == other_details.api_path_normalized
                and details.api_response_code == other_details.api_response_code
                and details.api_method == other_details.api_method
                and details.api_response_code == other_details.api_response_code
            )
        if isinstance(details, GoTestResourceCheckError):
            assert isinstance(other_details, GoTestResourceCheckError)
            return (
                details.tf_resource_name == other_details.tf_resource_name
                and details.tf_resource_type == other_details.tf_resource_type
                and details.step_nr == other_details.step_nr
                and details.check_numbers_str == other_details.check_numbers_str
            )
        return False

    @classmethod
    def group_by_classification(
        cls, errors: list[GoTestError], *, classifier: Literal["bot", "human"] = "human"
    ) -> ErrorClassified:
        def get_classification(error: GoTestError) -> GoTestErrorClass:
            if classifier == "bot":
                return error.bot_error_class
            return error.human_error_class

        grouped_errors: dict[GoTestErrorClass, list[GoTestError]] = iter_utils.group_by_once(
            errors, key=get_classification
        )
        unclassified = grouped_errors.pop(GoTestErrorClass.UNCLASSIFIED, [])
        return ErrorClassified(grouped_errors, unclassified)

    @classmethod
    def group_by_name_with_package(cls, errors: list[GoTestError]) -> dict[str, list[GoTestError]]:
        def by_name(error: GoTestError) -> str:
            return error.run.name_with_package

        return iter_utils.group_by_once(errors, key=by_name)

    @property
    def short_description(self) -> str:
        details = self.details
        return details_short_description(details) if details else ""

    def header(self, use_ticks: bool = False) -> str:
        name_with_ticks = f"`{self.run.name_with_package}`" if use_ticks else self.run.name_with_package
        if details := self.short_description:
            return f"{name_with_ticks} {details}"
        return f"{name_with_ticks}"


def details_short_description(details: ErrorDetailsT) -> str:
    match details:
        case GoTestGeneralCheckError():
            return str(details)
        case GoTestResourceCheckError():
            return f"CheckFailure for {details.tf_resource_type}.{details.tf_resource_name} at Step: {details.step_nr} Checks: {details.check_numbers_str}"
        case GoTestAPIError(api_path_normalized=api_path_normalized) if api_path_normalized:
            return f"API Error {details.api_error_code_str} {api_path_normalized}"
        case GoTestAPIError(api_path=api_path):
            return f"{details.api_error_code_str} {api_path}"
    return ""


one_of_methods = "|".join(API_METHODS)


check_pattern_str = r"Check (?P<check_nr>\d+)/\d+"
check_pattern = re.compile(check_pattern_str)
url_pattern = r"https://cloud(-dev|-qa)?\.mongodb\.com(?P<api_path>\S+)"
error_check_pattern = re.compile(check_pattern_str + r"\s+error:\s(?P<error_check_str>.+)$", re.MULTILINE)
detail_patterns: list[re.Pattern] = [
    re.compile(r"Step (?P<step_nr>\d+)/\d+"),
    check_pattern,
    re.compile(r"mongodbatlas_(?P<tf_resource_type>[^\.]+)\.(?P<tf_resource_name>[\w_-]+)"),
    re.compile(rf"(?P<api_method>{one_of_methods})" + r": HTTP (?P<api_response_code>\d+)"),
    re.compile(r'Error code: "(?P<api_error_code_str>[^"]+)"'),
    re.compile(url_pattern),
]

# Error: error creating MongoDB Cluster: POST https://cloud-dev.mongodb.com/api/atlas/v1.0/groups/680ecbc7122f5b15cc627ba5/clusters: 409 (request "OUT_OF_CAPACITY") The requested region is currently out of capacity for the requested instance size.
api_error_pattern_missing_details = re.compile(
    rf"(?P<api_method>{one_of_methods})\s+"
    + url_pattern
    + r'\s+(?P<api_response_code>\d+)\s\(request\s"(?P<api_error_code_str>[^"]+)"\)'
)


def parse_error_details(run: GoTestRun) -> ErrorDetailsT:
    kwargs = {}
    output = run.output_lines_str
    for pattern in detail_patterns:
        if pattern_match := pattern.search(output):
            kwargs |= pattern_match.groupdict()
    match kwargs:
        case {"api_path": _, "api_error_code_str": _}:
            return GoTestAPIError(**kwargs)
        case {"api_path": _} if pattern_match := api_error_pattern_missing_details.search(output):
            kwargs |= pattern_match.groupdict()
            return GoTestAPIError(**kwargs)
        case {"check_nr": _} if all(name in kwargs for name in ("tf_resource_name", "tf_resource_type")):
            kwargs.pop("check_nr")
            check_errors = CheckError.parse_from_output(output)
            return GoTestResourceCheckError(**kwargs, check_errors=check_errors)
        case {"check_nr": _}:
            if error_check_match := error_check_pattern.search(output):
                kwargs.pop("check_nr")
                check_errors = CheckError.parse_from_output(output)
                return GoTestGeneralCheckError(
                    **kwargs, error_check_str=error_check_match.group("error_check_str"), check_errors=check_errors
                )
    kwargs.pop("error_check_str", None)  # Remove if it was not matched
    return GoTestDefaultError(error_str=run.output_lines_str)
