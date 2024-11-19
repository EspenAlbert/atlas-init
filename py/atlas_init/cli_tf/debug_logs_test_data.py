import logging
from collections.abc import Callable

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
        return "__".join([self.method, self.path, self.version, self.text])  # noqa: FLY002


class StepRequests(Entity):
    diff_requests: list[RequestInfo] = Field(default_factory=list)
    request_responses: list[RequestInfo] = Field(default_factory=list)

    def existing_request(self, info: RequestInfo) -> RequestInfo | None:
        return next((r for r in self.request_responses if r.id == info.id), None)

    def add_request(
        self, path: str, method: str, version: str, status: int, text: str, text_response: str, is_diff: bool
    ):
        status_text = StatusText(status=status, text=text_response)
        info = RequestInfo(path=path, method=method, version=version, text=text, responses=[status_text])
        if is_diff:
            self.diff_requests.append(info)
        if existing := self.existing_request(info):
            existing.responses.append(status_text)
        else:
            self.request_responses.append(info)


class TestData(Entity):
    step_count: int
    steps: list[StepRequests] = Field(default_factory=list, init=False)
    variables: dict[str, str] = Field(default_factory=dict)

    @model_validator(mode="after")
    def set_steps(self):
        self.steps = [StepRequests() for _ in range(self.step_count)]
        return self

    def add_roundtrip(
        self, rt: SDKRoundtrip, normalized_path: str, normalized_text: str, normalized_response_text: str, is_diff: bool
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
    for api_spec_path in api_spec_paths:
        if api_spec_path.match(path):
            return api_spec_path
    raise ValueError(f"Could not find path: {path}")


def normalize_text(text: str, variables: dict[str, str]) -> str:
    for var, value in variables.items():
        text = text.replace(value, f"{{{var}}}")
    return text


def create_test_data(
    roundtrips: list[SDKRoundtrip],
    api_spec_paths: dict[str, list[ApiSpecPath]],
    is_diff: Callable[[SDKRoundtrip], bool] | None = None,
) -> TestData:
    steps = max(rt.step_number for rt in roundtrips)
    requests = TestData(step_count=steps)
    is_diff = is_diff or (lambda rt: rt.request.method != "GET")
    for rt in roundtrips:
        request_path = rt.request.path
        method = rt.request.method
        spec_path = find_normalized_path(request_path, api_spec_paths[method])
        rt_variables = spec_path.variables(request_path)
        normalized_path = spec_path.path
        normalized_text = normalize_text(rt.request.text, rt_variables)
        normalized_response_text = normalize_text(rt.response.text, rt_variables)

        requests.variables.update(rt_variables)
        requests.add_roundtrip(rt, normalized_path, normalized_text, normalized_response_text, is_diff(rt))
    requests.prune_duplicate_responses()
    return requests
