from __future__ import annotations

from functools import total_ordering
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, NamedTuple, TypeAlias

from model_lib import Entity
from pydantic import Field, model_validator
from zero_3rdparty import iter_utils

from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.repos.go_sdk import ApiSpecPaths


class GoTestErrorClass(StrEnum):
    """Goal of each error class to be actionable."""

    FLAKY_400 = "flaky_400"
    FLAKY_500 = "flaky_500"
    FLAKY_CHECK = "flaky_check"
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
        FLAKY_500: ("HTTP 500", "UNEXPECTED_ERROR"),
        PROVIDER_DOWNLOAD: tuple("mongodbatlas: failed to retrieve authentication checksums for provider".split()),
    }

    @classmethod
    def auto_classification(cls, output: str) -> GoTestErrorClass | None:
        return next(
            (
                error_class
                for error_class, contains_list in cls.__CONTAINS_MAPPING__.items()
                if all(contains in output for contains in contains_list)
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
        path = self.api_path
        method = self.api_method
        if api_paths := info.paths:
            self.api_path_normalized = api_paths.normalize_path(method, path)

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


class GoTestCheckError(Entity):
    type: Literal["check_error"] = "check_error"
    tf_resource_name: str
    tf_resource_type: str
    step_nr: int = -1
    check_errors: list[CheckError] = Field(default_factory=list)

    def add_info_fields(self, _: DetailsInfo) -> None:
        pass

    def __str__(self) -> str:
        return f"{self.tf_resource_type} {self.tf_resource_name} {self.step_nr} {self.check_errors}"

    @property
    def check_numbers_str(self) -> str:
        return ",".join(str(check.check_nr) for check in sorted(self.check_errors))


@dataclass
class DetailsInfo:
    run: GoTestRun
    paths: ApiSpecPaths | None = None


class GoTestDefaultError(Entity):
    type: Literal["default_error"] = "default_error"
    error_str: str

    def add_info_fields(self, _: DetailsInfo) -> None:
        pass


ErrorDetails: TypeAlias = GoTestAPIError | GoTestCheckError | GoTestDefaultError


class ErrorClassified(NamedTuple):
    classified: dict[GoTestErrorClass, list[GoTestError]]
    unclassified: list[GoTestError]


@total_ordering
class GoTestError(Entity):
    details: ErrorDetails
    run: GoTestRun
    bot_error_class: GoTestErrorClass = GoTestErrorClass.UNCLASSIFIED
    human_error_class: GoTestErrorClass = GoTestErrorClass.UNCLASSIFIED

    def __lt__(self, other) -> bool:
        if not isinstance(other, GoTestError):
            raise TypeError
        return self.run < other.run

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
        if isinstance(details, GoTestCheckError):
            assert isinstance(other_details, GoTestCheckError)
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


one_of_methods = "|".join(API_METHODS)


check_pattern = re.compile(r"Check (?P<check_nr>\d+)/\d+")
url_pattern = r"https://cloud(-dev|-qa)?\.mongodb\.com(?P<api_path>\S+)"
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


def parse_error_details(run: GoTestRun) -> ErrorDetails:
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
        case {"check_nr": _}:
            kwargs.pop("check_nr")
            check_errors = [
                CheckError(**check_match.groupdict())  # type: ignore
                for check_match in check_pattern.finditer(output)
            ]
            return GoTestCheckError(**kwargs, check_errors=check_errors)
    return GoTestDefaultError(error_str=run.output_lines_str)
