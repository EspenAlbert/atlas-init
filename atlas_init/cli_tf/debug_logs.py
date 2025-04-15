import json
import logging
import re
from contextlib import suppress
from functools import total_ordering
from typing import Any, NamedTuple, Self

from model_lib import Entity
from pydantic import ValidationError, model_validator

logger = logging.getLogger(__name__)


def parsed(payload: str) -> tuple[dict[str, Any] | None, list | None, bool | None]:
    with suppress(ValueError):
        resp = json.loads(payload)
        if isinstance(resp, dict):
            return resp, None, None
        if isinstance(resp, list):
            return None, resp, None
    if payload.strip() in {"true", "false"}:
        return None, None, payload.strip() == "true"
    raise ValueError(f"Could not parse payload: {payload}")


class PathHeadersPayload(Entity):
    method: str
    path: str
    http_protocol: str
    headers: dict[str, str]
    text: str

    @property
    def expect_list_response(self) -> bool:
        final_path = self.path.split("/")[-1]
        if final_path in {"settings", "processArgs"}:
            return False
        return self.method == "GET" and self.path.endswith("s") and all(not c.isdigit() for c in final_path)

    @model_validator(mode="after")
    def normalize_path(self) -> Self:
        if "?" in self.path:
            self.path = self.path.split("?", 1)[0]
        return self


def parse_request(request_lines: list[str]) -> PathHeadersPayload:
    path_line, *header_lines_payload = request_lines
    headers_end = header_lines_payload.index("")
    header_lines = header_lines_payload[:headers_end]
    payload_lines = header_lines_payload[headers_end + 1 :]
    payload_end = payload_lines.index("")
    payload_lines = payload_lines[:payload_end]
    method, path, http_protocol = path_line.split(" ")
    return PathHeadersPayload(
        method=method,
        http_protocol=http_protocol,
        path=path,
        headers=dict(header_line.split(": ", 1) for header_line in header_lines),
        text="\n".join(payload_lines),
    )


class StatusHeadersResponse(Entity):
    http_protocol: str
    status: int
    status_text: str
    headers: dict[str, str]
    text: str


def parse_response(response_lines: list[str]) -> StatusHeadersResponse:
    http_protocol_status, *header_lines_response = response_lines
    http_protocol, status, status_text = http_protocol_status.split(" ", 2)
    headers_end = header_lines_response.index("")
    header_lines = header_lines_response[:headers_end]
    response = header_lines_response[headers_end + 1 :]
    return StatusHeadersResponse(
        http_protocol=http_protocol,
        status=status,  # type: ignore
        status_text=status_text,
        headers=dict(header_line.split(": ", 1) for header_line in header_lines),
        text="\n".join(response),
    )


# application/vnd.atlas.2024-08-05+json;charset=utf-8

_version_date_pattern = re.compile(r"(\d{4}-\d{2}-\d{2})")


def extract_version(content_type: str) -> str:
    if match := _version_date_pattern.search(content_type):
        return match.group(1)
    raise ValueError(f"Could not extract version from {content_type} header")


@total_ordering
class SDKRoundtrip(Entity):
    request: PathHeadersPayload
    response: StatusHeadersResponse
    resp_index: int
    step_number: int

    @property
    def id(self) -> str:
        return f"{self.request.method}_{self.request.path}_{self.version}"

    @property
    def version(self) -> str:
        content_type = self.response.headers.get("Content-Type", "v1")
        content_type_req = self.request.headers.get("Accept", "v1")
        with suppress(ValueError):
            return extract_version(content_type)
        with suppress(ValueError):
            return extract_version(content_type_req)
        raise ValueError(f"Could not extract version from req/resp: {content_type} or {content_type_req}")

    @property
    def java_method_match(self) -> bool:
        java_method = self.response.headers.get("X-Java-Method")
        if not java_method:
            return False
        java_method_final = java_method.split("::")[-1]
        final_req_path = self.request.path.split("/")[-1]
        return final_req_path.lower() in java_method_final.lower()

    @model_validator(mode="after")
    def ensure_match(self) -> Self:
        if self.java_method_match:
            return self
        req = self.request
        resp = self.response
        resp_payload_dict, resp_payload_list, __ = parsed(resp.text)
        resp_payload_dict = resp_payload_dict or {}
        want_list = req.expect_list_response
        if want_list and resp_payload_list is None and "results" not in resp_payload_dict:
            raise ValueError(f"Expected list response but got dict: {resp.text}")
        if not want_list and (resp_payload_list or "results" in resp_payload_dict):
            raise ValueError(f"Expected dict response but got list: {resp.text}")
        return self

    def __lt__(self, other) -> bool:
        if not isinstance(other, SDKRoundtrip):
            raise TypeError
        return self.resp_index < other.resp_index


MARKER_END = "-----------------------------------"
MARKER_REQUEST_START = "---[ REQUEST ]"
MARKER_RESPONSE_START = "---[ RESPONSE ]----"
MARKER_START_STEP = "Starting TestStep: "
MARKER_TEST = "Starting TestSteps: "


class FileRef(NamedTuple):
    request_index: int
    line_start: int
    line_end: int


_name_extract = re.compile(r"test_name=(\S+)")


def parse_test_name(logs: str) -> str:
    test_count = logs.count(MARKER_TEST)
    assert test_count == 1, f"Only one test is supported, found {test_count}"
    test_start = logs.index(MARKER_TEST)
    full_line = logs[test_start:].split("\n", maxsplit=1)[0]
    if match := _name_extract.search(full_line):
        return match.group(1)
    raise ValueError(f"Could not extract test name from {full_line}")


def parse_http_requests(logs: str) -> list[SDKRoundtrip]:
    """
    Problem: With requests that are done in parallel.
    An alternative is to use parallel 1 but it will be slow
    Methods: (rejected)
    1. Look for match from `path` to the something in the payload
    2. Use the X-Java-Method header to match the response with the path
    3. X-Envoy-Upstream-Service-Time to match it

    Method: (accepted)
    Can say that expected payload is either a list or a dict and if it ends with an identifier it is higher chance for a dict
    """
    test_name = parse_test_name(logs)
    logger.info(f"Finding http requests for test name: '{test_name}'")
    requests, responses = parse_raw_req_responses(logs)
    tf_step_starts = [i for i, line in enumerate(logs.splitlines()) if MARKER_START_STEP in line]
    used_responses: set[int] = set()
    responses_list: list[StatusHeadersResponse] = list(responses.values())
    sdk_roundtrips = []
    for ref, request in requests.items():
        roundtrip = match_request(used_responses, responses_list, ref, request, tf_step_starts)
        sdk_roundtrips.append(roundtrip)
        used_responses.add(roundtrip.resp_index)
    return sorted(sdk_roundtrips)


def find_step_number(ref: FileRef, step_starts: list[int]) -> int:
    for i, step_start in enumerate(reversed(step_starts)):
        if step_start < ref.line_start:
            return len(step_starts) - i
    logger.warning(f"Could not find step start for {ref}")
    return 0


def match_request(
    used_responses: set[int],
    responses_list: list[StatusHeadersResponse],
    ref: FileRef,
    request: PathHeadersPayload,
    step_starts: list[int],
) -> SDKRoundtrip:
    for i, response in enumerate(responses_list):
        if i in used_responses:
            continue
        with suppress(ValidationError):
            step_number = find_step_number(ref, step_starts)
            return SDKRoundtrip(
                request=request,
                response=response,
                resp_index=i,
                step_number=step_number,
            )
    remaining_responses = [resp for i, resp in enumerate(responses_list) if i not in used_responses]
    err_msg = f"Could not match request {request.path} ({ref}) with any response\n\n{request}\n\n\nThere are #{len(remaining_responses)} responses left that doesn't match\n{'-' * 80}\n{'\n'.join(r.text for r in remaining_responses)}"
    raise ValueError(err_msg)


def parse_raw_req_responses(
    logs: str,
) -> tuple[dict[FileRef, PathHeadersPayload], dict[FileRef, StatusHeadersResponse]]:
    # sourcery skip: dict-comprehension
    request_count = 0
    response_count = 0
    in_request = False
    in_response = False
    current_start = 0
    requests: dict[FileRef, list[str]] = {}
    responses: dict[FileRef, list[str]] = {}
    log_lines = logs.splitlines()
    for i, line in enumerate(log_lines):
        if line.startswith(MARKER_REQUEST_START):
            in_request = True
            current_start = i + 1
        elif line.startswith(MARKER_RESPONSE_START):
            in_response = True
            current_start = i + 1
        if in_request and line.startswith(MARKER_END):
            key = FileRef(request_index=request_count, line_start=current_start, line_end=i)
            requests[key] = log_lines[current_start:i]
            request_count += 1
            in_request = False
        if in_response and line.startswith(MARKER_END):
            key = FileRef(request_index=request_count, line_start=current_start, line_end=i)
            responses[key] = log_lines[current_start:i]
            response_count += 1
            in_response = False
    assert not in_request, "Request not closed"
    assert not in_response, "Response not closed"
    assert request_count == response_count, (
        f"Mismatch in request and response count: {request_count} != {response_count}"
    )
    parsed_requests = {}
    for ref, request_lines in requests.items():
        parsed_requests[ref] = parse_request(request_lines)
    parsed_responses = {}
    for ref, response_lines in responses.items():
        parsed_responses[ref] = parse_response(response_lines)
    return parsed_requests, parsed_responses
