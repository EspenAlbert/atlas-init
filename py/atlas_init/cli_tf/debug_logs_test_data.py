import json
import logging
from collections.abc import Callable
from typing import NamedTuple

from model_lib import Entity
from pydantic import Field, model_validator

from atlas_init.cli_tf.debug_logs import SDKRoundtrip

logger = logging.getLogger(__name__)


class StatusText(Entity):
    status: int
    text: str

    @property
    def id(self):
        return f"{self.status}_{self.text}"


class RequestInfo(Entity):
    version: str
    method: str
    path: str
    text: str
    responses: list[StatusText] = Field(default_factory=list)

    @property
    def id(self):
        return "__".join(  # noqa: FLY002
            [
                self.method,
                self.path,
                self.version,
                self.text,
            ]  # need to include text to differentiate between requests
        )


class StepRequests(Entity):
    diff_requests: list[RequestInfo] = Field(default_factory=list)
    request_responses: list[RequestInfo] = Field(default_factory=list)

    def existing_request(self, info: RequestInfo) -> RequestInfo | None:
        return next((r for r in self.request_responses if r.id == info.id), None)

    def add_request(
        self,
        path: str,
        method: str,
        version: str,
        status: int,
        text: str,
        text_response: str,
        is_diff: bool,
    ):
        status_text = StatusText(status=status, text=text_response)
        info = RequestInfo(
            path=path,
            method=method,
            version=version,
            text=text,
            responses=[status_text],
        )
        if is_diff:
            self.diff_requests.append(info)
        if existing := self.existing_request(info):
            existing.responses.append(status_text)
        else:
            self.request_responses.append(info)


class RTModifier(Entity):
    version: str
    method: str
    path: str
    modification: Callable[[SDKRoundtrip], None]

    def match(self, rt: SDKRoundtrip, normalized_path: str) -> bool:
        return rt.request.method == self.method and normalized_path == self.path and rt.version == self.version


class MockRequestData(Entity):
    step_count: int
    steps: list[StepRequests] = Field(default_factory=list, init=False)
    variables: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def set_steps(self):
        self.steps = [StepRequests() for _ in range(self.step_count)]
        return self

    def add_roundtrip(
        self,
        rt: SDKRoundtrip,
        normalized_path: str,
        normalized_text: str,
        normalized_response_text: str,
        is_diff: bool,
    ):
        step = self.steps[rt.step_number - 1]
        if rt.request.method == "PATCH":
            logger.info(f"PATCH: {rt.request.path}")
        step.add_request(
            normalized_path,
            rt.request.method,
            rt.version,
            rt.response.status,
            normalized_text,
            normalized_response_text,
            is_diff,
        )

    def update_variables(self, variables: dict[str, str]) -> None:
        if missing_value := sorted(name for name, value in variables.items() if not value):
            err_msg = f"Missing values for variables: {missing_value}"
            raise ValueError(err_msg)
        changes: list[VariableChange] = []
        for name, value in variables.items():
            old_value = self.variables.get(name)
            if old_value and old_value != value:
                for suffix in range(2, 10):
                    new_name = f"{name}{suffix}"
                    old_value2 = self.variables.get(new_name, "")
                    if old_value2 and old_value2 != value:
                        continue
                    if not old_value2:
                        logger.warning(f"Adding variable {name} to {new_name}={value}")
                    change = VariableChange(name, new_name, old_value, value)
                    changes.append(change)
                    self.variables[new_name] = value
                    break
                else:
                    raise ValueError(f"Too many variables with the same name and different values: {name}")
            else:
                self.variables[name] = value
        if changes:
            raise VariablesChangedError(changes)

    def prune_duplicate_responses(self):
        for step in self.steps:
            for request in step.request_responses:
                pruned_responses = []
                seen_response_ids = set()
                before_len = len(request.responses)
                for response in request.responses:
                    if response.id in seen_response_ids:
                        continue
                    seen_response_ids.add(response.id)
                    pruned_responses.append(response)
                request.responses = pruned_responses
                after_len = len(request.responses)
                if before_len != after_len:
                    logger.info(f"Pruned {before_len - after_len} duplicate responses from {request.id}")


class ApiSpecPath(Entity):
    path: str

    def variables(self, path: str) -> dict[str, str]:
        return {
            var[1:-1]: default
            for var, default in zip(self.path.split("/"), path.split("/"), strict=False)
            if var.startswith("{") and var.endswith("}")
        }

    def match(self, path: str) -> bool:
        parts_expected = self.path.split("/")
        parts_actual = path.split("/")
        if len(parts_expected) != len(parts_actual):
            return False
        for expected, actual in zip(parts_expected, parts_actual, strict=False):
            if expected == actual:
                continue
            if expected.startswith("{") and expected.endswith("}"):
                continue
            return False
        return True


def find_normalized_path(path: str, api_spec_paths: list[ApiSpecPath]) -> ApiSpecPath:
    if "?" in path:
        path = path.split("?")[0]
    path = path.rstrip("/")  # remove trailing slash
    for api_spec_path in api_spec_paths:
        if api_spec_path.match(path):
            return api_spec_path
    raise ValueError(f"Could not find path: {path}")


def normalize_text(text: str, variables: dict[str, str]) -> str:
    for var, value in variables.items():
        text = text.replace(value, f"{{{var}}}")
    if not text:
        return text
    try:
        parsed_text = json.loads(text)
        return json.dumps(parsed_text, indent=1, sort_keys=True)
    except json.JSONDecodeError:
        logger.warning(f"Could not parse text: {text}")
        return text


def default_is_diff(rt: SDKRoundtrip) -> bool:
    return rt.request.method not in {"DELETE", "GET"}


class VariableChange(NamedTuple):
    var_name: str
    new_var_name: str
    old: str
    new: str


class VariablesChangedError(Exception):
    def __init__(self, changes: list[VariableChange]) -> None:
        super().__init__(f"Variables changed: {changes}")
        self.changes = changes


def create_mock_data(
    roundtrips: list[SDKRoundtrip],
    api_spec_paths: dict[str, list[ApiSpecPath]],
    is_diff: Callable[[SDKRoundtrip], bool] | None = None,
    modifiers: list[RTModifier] | None = None,
) -> MockRequestData:
    steps = max(rt.step_number for rt in roundtrips)
    mock_data = MockRequestData(step_count=steps)
    is_diff = is_diff or default_is_diff
    modifiers = modifiers or []
    for rt in roundtrips:
        request_path = rt.request.path
        method = rt.request.method
        spec_path = find_normalized_path(request_path, api_spec_paths[method])
        rt_variables = spec_path.variables(request_path)
        normalized_path = spec_path.path
        try:
            mock_data.update_variables(rt_variables)
        except VariablesChangedError as e:
            for change in e.changes:
                rt_variables.pop(change.var_name)
                rt_variables[change.new_var_name] = change.new
            normalized_path = normalize_text(request_path, rt_variables)
        for modifier in modifiers:
            if modifier.match(rt, normalized_path):
                modifier.modification(rt)
        normalized_text = normalize_text(rt.request.text, rt_variables)
        normalized_response_text = normalize_text(rt.response.text, rt_variables)
        mock_data.add_roundtrip(rt, normalized_path, normalized_text, normalized_response_text, is_diff(rt))
    # requests.prune_duplicate_responses() better to keep duplicates to stay KISS
    return mock_data
