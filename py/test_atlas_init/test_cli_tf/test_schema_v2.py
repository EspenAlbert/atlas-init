import logging

import pytest

from atlas_init.cli_tf.schema_v2 import (
    SchemaAttribute,
    SchemaV2,
    attr_path_matches,
    extend_import_urls,
    generate_go_resource_schema,
    import_lines,
    plan_modifiers_lines,
)
from atlas_init.cli_tf.schema_v2_api_parsing import (
    add_api_spec_info,
)

logger = logging.getLogger(__name__)


def _id_attribute(schema: SchemaV2) -> SchemaAttribute:
    processor = schema.resources["stream_processor"]
    return processor.attributes["id"]


def test_schema_v2(schema_v2):
    assert schema_v2.resources
    processor = schema_v2.resources["stream_processor"]
    assert processor.name == "stream_processor"
    assert processor.paths == [
        "/api/atlas/v2/groups/{groupId}/streams/{tenantName}/processor",
        "/api/atlas/v2/groups/{groupId}/streams/{tenantName}/processor/{processorName}",
    ]
    assert processor.attributes
    id_attribute = processor.attributes["id"]
    assert id_attribute.name == "id"
    assert id_attribute.aliases == ["_id"]
    assert id_attribute.plan_modifiers == ["UseStateForUnknown"]


def test_plan_modifiers_lines(schema_v2):
    id_attribute = _id_attribute(schema_v2)
    actual = plan_modifiers_lines(id_attribute, 0)
    assert actual == [
        "PlanModifiers: []planmodifier.String{",
        "  stringplanmodifier.UseStateForUnknown(),",
        "},",
    ]


def test_add_api_spec_info(schema_v2, api_spec_path):
    add_api_spec_info(schema_v2, api_spec_path)
    resource = schema_v2.resources["stream_processor"]
    assert resource.attributes["id"].plan_modifiers == ["UseStateForUnknown"]
    assert sorted(resource.attributes) == [
        "id",
        "instance_name",
        "options",
        "pipeline",
        "processor_name",
        "project_id",
        "state",
        "stats",
    ]


@pytest.mark.parametrize("resource_name", ["stream_processor", "resource_policy"])
def test_resource_schema_full(
    schema_with_api_info: SchemaV2, resource_name, file_regression
):
    schema = schema_with_api_info
    actual = generate_go_resource_schema(schema, schema.resources[resource_name])
    file_regression.check(actual, basename=resource_name, extension=".go")


_expected_import_lines = """\
import (
  "context"

  "github.com/hashicorp/terraform-plugin-framework/resource/schema"
  "github.com/hashicorp/terraform-plugin-framework/schema/validator"
)
"""


def test_extend_import_urls():
    lines = [
        "ctx context.Context",
        '"state": schema.StringAttribute{"',
        "Validators: []validator.String{",
        "				Required:            true,",
    ]
    import_urls = set()
    extend_import_urls(import_urls, lines)
    actual_lines = import_lines(import_urls)
    actual = "\n".join(actual_lines)
    assert actual == _expected_import_lines


def test_attr_path_matches():
    assert attr_path_matches("foo", "foo")
    assert attr_path_matches("foo.bar", "foo.bar")
    assert attr_path_matches("foo.bar", "foo.*")
    assert attr_path_matches("foo.bar.next", "foo.*")
    assert not attr_path_matches("foo.bar", "foo")
