import contextlib
import logging
import os
import re
from pathlib import Path

import pytest
from model_lib import dump, parse_model, parse_payload
from zero_3rdparty import file_utils

from atlas_init.cli_tf.schema_v2 import SchemaV2
from atlas_init.cli_tf.schema_v2_api_parsing import (
    OpenapiSchema,
    api_spec_text_changes,
    extract_api_version_content_header,
    minimal_api_spec,
    parse_api_spec_param,
)

from atlas_init.settings.env_vars import AtlasInitSettings

logger = logging.getLogger(__name__)


def test_openapi_schema_create_parameters(schema_v2: SchemaV2, openapi_schema: OpenapiSchema):
    processor = schema_v2.resources["stream_processor"]
    create_path, read_path = processor.paths
    create_method = openapi_schema.create_method(create_path)
    assert create_method
    assert openapi_schema.read_method(read_path)
    create_path_params = create_method.get("parameters", [])
    assert len(create_path_params) == 2
    group_id_param, tenant_name_param = create_path_params
    assert group_id_param == {"$ref": "#/components/parameters/groupId"}
    project_id_param = parse_api_spec_param(openapi_schema, group_id_param, processor)
    assert project_id_param
    assert project_id_param.name == "project_id"
    assert project_id_param.type == "string"
    assert project_id_param.description
    assert project_id_param.is_required
    assert tenant_name_param == {
        "description": "Human-readable label that identifies the stream instance.",
        "in": "path",
        "name": "tenantName",
        "required": True,
        "schema": {"type": "string"},
    }
    instance_name_param = parse_api_spec_param(openapi_schema, tenant_name_param, processor)
    assert instance_name_param
    assert instance_name_param.name == "instance_name"
    assert instance_name_param.type == "string"
    assert instance_name_param.description
    assert instance_name_param.is_required

    req_ref = openapi_schema.method_request_body_ref(create_method)
    assert req_ref == "#/components/schemas/StreamsProcessor"
    property_dicts = list(openapi_schema.schema_properties(req_ref))
    assert property_dicts
    assert sorted(d["name"] for d in property_dicts) == [
        "_id",
        "links",
        "name",
        "options",
        "pipeline",
    ]


def test_openapi_schema_read_parameters(schema_v2, openapi_schema: OpenapiSchema):
    processor = schema_v2.resources["stream_processor"]
    read_path = processor.paths[1]
    read_method = openapi_schema.read_method(read_path)
    assert read_method
    read_path_params = read_method.get("parameters", [])
    assert len(read_path_params) == 3
    group_id_param, tenant_name_param, processor_name_param = read_path_params
    assert group_id_param == {"$ref": "#/components/parameters/groupId"}
    assert tenant_name_param["name"] == "tenantName"
    assert processor_name_param["name"] == "processorName"
    response_ref = openapi_schema.method_response_ref(read_method)
    assert response_ref == "#/components/schemas/StreamsProcessorWithStats"
    property_dicts = list(openapi_schema.schema_properties(response_ref))
    assert property_dicts
    assert sorted(d["name"] for d in property_dicts) == [
        "_id",
        "links",
        "name",
        "options",
        "pipeline",
        "state",
        "stats",
    ]


def test_openapi_schema_read_parameters_array(schema_v2, openapi_schema: OpenapiSchema):
    resource_policy = schema_v2.resources["resource_policy"]
    assert resource_policy
    ref = "#/components/schemas/ResourcePolicyCreate"
    schema_properties = list(openapi_schema.schema_properties(ref))
    assert sorted(d["name"] for d in schema_properties) == [
        "name",
        "policies",
    ]
    policies = [d for d in schema_properties if d["name"] == "policies"][0]
    schema_attribute = parse_api_spec_param(openapi_schema, policies, resource_policy)
    assert schema_attribute, "unable to infer attribute for policies"
    assert schema_attribute.type == "array"
    assert schema_attribute.schema_ref == "#/components/schemas/Policy"
    assert schema_attribute.is_nested


@pytest.mark.skipif(os.environ.get("API_SPEC_PATH", "") == "", reason="needs os.environ[API_SPEC_PATH]")
def test_ensure_test_data_admin_api_is_up_to_date(schema_v2, file_regression, api_spec_path):
    api_path = Path(os.environ["API_SPEC_PATH"])
    openapi_schema = parse_model(api_path, t=OpenapiSchema)
    assert openapi_schema, "unable to parse admin api spec"
    if api_spec_path.suffix not in [".yaml", ".yml"]:
        parsed_raw = parse_payload(api_path)
        spec_yaml = dump(parsed_raw, "yaml")
        api_path.with_name(f"{api_path.stem}.yaml").write_text(spec_yaml)
    minimal_spec = minimal_api_spec(schema_v2, api_path)
    minimal_spec_yaml = dump(minimal_spec, "yaml")
    file_regression.check(minimal_spec_yaml, fullpath=api_spec_path)


def test_api_spec_text_changes(schema_v2, openapi_schema, file_regression):
    updated = api_spec_text_changes(schema_v2, openapi_schema)
    updated_yaml = dump(updated, "yaml")
    file_regression.check(updated_yaml, basename="openapi_text_changes", extension=".yaml")


@pytest.mark.skipif(os.environ.get("API_SPEC_PATH", "") == "", reason="needs os.environ[API_SPEC_PATH]")
def test_invalid_in_regex_patterns():
    api_path = Path(os.environ["API_SPEC_PATH"])
    expected_count = 1033
    should_not_match = "ac/b"
    project_id_example_pattern = re.compile("^([a-f0-9]{24})$")
    assert not project_id_example_pattern.match(should_not_match)
    assert not pattern_match_full("[0-9a-f]+", should_not_match)
    patterns = find_patterns_in_file_and_match(api_path, should_not_match)
    assert len(patterns) == expected_count, f"expected {expected_count} patterns, got {len(patterns)}"


def find_patterns_in_file_and_match(api_path: Path, expected_no_match: str) -> list[str]:
    patterns = []
    lines = api_path.read_text().splitlines()
    prefix = 'pattern: "'
    for i, line in enumerate(lines):
        if prefix in line:
            pattern_value = line.split(prefix)[1].strip()
            # handle multi line patterns
            j = 0
            while not pattern_value.endswith('"'):
                j += 1
                pattern_value += lines[i + j].strip().rstrip("\\")
            pattern_value = pattern_value.rstrip('"')
            patterns.append(pattern_value)
            pattern_value = valid_pattern(pattern_value)
            if not pattern_value:
                logger.warning(f"invalid pattern: {patterns[-1]} on line: {i + 1}")
                continue
            if pattern_match_full(pattern_value, expected_no_match):
                logger.warning(f"pattern: {pattern_value} matched invalid character: {expected_no_match} on L={i + 1}")
    return patterns


def valid_pattern(pattern: str) -> str:
    # some patterns are invalid for python re.compile, try to fix them
    for c in [pattern, pattern.replace("\\\\", "\\"), pattern.replace("?<", "?P<")]:
        with contextlib.suppress(re.error):
            re.compile(c)
            return c
    return ""


def pattern_match_full(pattern: str, text: str) -> bool:
    # avoid any partial matches (e.g., start of string matches)
    compiled = re.compile(pattern)
    m = compiled.match(text)
    return m is not None and m[0] == text


def find_patterns_in_file_regex(api_path: Path) -> list[str]:
    text = api_path.read_text()
    pattern_regex = re.compile(r'\s+pattern:\s+"(?P<pattern>[^"]*)"$\s*', re.MULTILINE)
    return pattern_regex.findall(text)


def test_extract_api_version_content_header():
    assert extract_api_version_content_header("application/vnd.atlas.2023-01-01+json") == "2023-01-01"


@pytest.mark.skipif(os.environ.get("API_SPEC_PATH", "") == "", reason="needs os.environ[API_SPEC_PATH]")
@pytest.mark.skipif(os.environ.get("LIVE_STATIC_DIR", "") == "", reason="needs os.environ[LIVE_STATIC_DIR]")
def test_finding_multiple_response_versions():
    api_path = Path(os.environ["API_SPEC_PATH"])
    logger.info(f"parsing admin api spec: {api_path}")
    model = parse_model(api_path, t=OpenapiSchema)
    assert model, "unable to parse admin api spec"
    settings = AtlasInitSettings(STATIC_DIR=os.environ["LIVE_STATIC_DIR"])  # type: ignore
    report_path = settings.static_root / "api_versions_report.md"
    report_md = generate_api_versions_report(model)
    file_utils.ensure_parents_write_text(report_path, "\n".join(report_md))
    logger.info(f"report written to: {report_path}")


def generate_api_versions_report(model: OpenapiSchema) -> list[str]:
    counter = 0
    unique_versions = set()
    headers = ["Path", "Method", "Code", "Versions"]
    report_md = [
        " | ".join(headers),
        " | ".join(["---"] * len(headers)),
    ]
    multiple_versions_counter = 0
    for (path, method, code), versions in model.path_method_api_versions():
        counter += 1
        unique_versions.update(versions)
        if len(versions) > 1:
            logger.warning(f"multiple versions for {path} {method} {code}: {versions}")
            report_md.append(f"{path} | {method} | {code} | {', '.join(sorted(versions))}")
            multiple_versions_counter += 1
    versions_sorted = "\n".join(sorted(unique_versions))
    logger.info(
        f"found {counter} paths with {len(unique_versions)} unique API versions, where {multiple_versions_counter} used more than one version:\n{versions_sorted} "
    )
    return report_md
