from dataclasses import dataclass
from enum import StrEnum
from functools import singledispatch
import re
from typing import Literal, TypeAlias

from model_lib import Entity
from pydantic import Field

from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.repos.go_sdk import ApiSpecPaths


class GoTestErrorClass(StrEnum):
    """Goal of each error class to be actionable."""

    FLAKY_400 = "flaky_400"
    FLAKY_500 = "flaky_400"
    FLAKY_CHECK = "flaky_check"
    OUT_OF_CAPACITY = "out_of_capacity"
    PROJECT_LIMIT_EXCEEDED = "project_limit_exceeded"
    DANGLING_RESOURCE = "dangling_resource"
    REAL_TEST_FAILURE = "real_test_failure"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"

    __ACTIONS__ = {
        FLAKY_400: "retry",
        FLAKY_500: "retry",
        FLAKY_CHECK: "retry",
        OUT_OF_CAPACITY: "retry_later",
        PROJECT_LIMIT_EXCEEDED: "clean_project",
        DANGLING_RESOURCE: "update_cleanup_script",
        REAL_TEST_FAILURE: "investigate",
        TIMEOUT: "investigate",
        UNKNOWN: "investigate",
    }


API_METHODS = ["GET", "POST", "PUT", "DELETE", "PATCH"]


class GoTestAPIError(Entity):
    type: Literal["api_error"] = "api_error"
    api_error_code_str: str
    api_path: str
    api_method: Literal["GET", "POST", "PUT", "DELETE", "PATCH"]
    api_response_code: int
    tf_resource_name: str
    tf_resource_type: str
    step_nr: int = -1


class CheckError(Entity):
    attribute: str = ""
    expected: str = ""
    got: str = ""
    check_nr: int = -1


class GoTestCheckError(Entity):
    type: Literal["check_error"] = "check_error"
    tf_resource_name: str
    tf_resource_type: str
    step_nr: int = -1
    check_errors: list[CheckError] = Field(default_factory=list)


@dataclass
class DetailsInfo:
    run: GoTestRun
    paths: ApiSpecPaths | None = None


@singledispatch
def details_test_id(details: object, info: DetailsInfo) -> str:
    return ""


@details_test_id.register
def _check_test_id(details: GoTestCheckError, info: DetailsInfo) -> str:
    run = info.run
    check_nrs = ",".join(str(check.check_nr) for check in details.check_errors)
    return f"{run.package_rel_path}/{run.name}#Step={details.step_nr}Checks={check_nrs}"


@singledispatch
def details_api_id(details: object, info: DetailsInfo) -> str:
    return ""


@details_api_id.register
def _go_test_api_id(details: GoTestAPIError, info: DetailsInfo) -> str:
    path = details.api_path
    method = details.api_method
    if api_paths := info.paths:
        path = api_paths.normalize_path(method, path)
    return "__".join([method, str(details.api_response_code), details.api_error_code_str, path])


class GoTestDefaultError(Entity):
    type: Literal["default_error"] = "default_error"
    error_str: str


ErrorDetails: TypeAlias = GoTestAPIError | GoTestCheckError | GoTestDefaultError


class GoTestError(Entity):
    details: ErrorDetails
    bot_error_class: GoTestErrorClass
    human_error_class: GoTestErrorClass | None = None


one_of_methods = "|".join(API_METHODS)


check_pattern = re.compile(r"Check (?P<check_nr>\d+)/\d+")
detail_patterns: list[re.Pattern] = [
    re.compile(r"Step (?P<step_nr>\d+)/\d+"),
    check_pattern,
    re.compile(r"mongodbatlas_(?P<tf_resource_type>[^\.]+)\.(?P<tf_resource_name>[\w_-]+)"),
    re.compile(r"Params: \[(?P<api_path>[^\]]+)\]"),
    re.compile(rf"(?P<api_method>{one_of_methods})" + r": HTTP (?P<api_response_code>\d+)"),
    re.compile(r'Error code: "(?P<api_error_code_str>[^"]+)"'),
]


def extract_error_details(run: GoTestRun) -> ErrorDetails:
    kwargs = {}
    output = run.output_lines_str
    for pattern in detail_patterns:
        if pattern_match := pattern.search(output):
            kwargs |= pattern_match.groupdict()
    match kwargs:
        case {"api_path": _}:
            return GoTestAPIError(**kwargs)
        case {"check_nr": _}:
            kwargs.pop("check_nr")
            check_errors = [
                CheckError(**check_match.groupdict())  # type: ignore
                for check_match in check_pattern.finditer(output)
            ]
            return GoTestCheckError(**kwargs, check_errors=check_errors)
    return GoTestDefaultError(error_str=run.output_lines_str)
