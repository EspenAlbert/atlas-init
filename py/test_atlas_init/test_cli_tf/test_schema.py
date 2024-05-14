from pathlib import Path

from model_lib import parse_model

from atlas_init.cli_tf.schema import (
    ProviderCodeSpec,
    PyTerraformSchema,
    dump_generator_config,
    parse_py_terraform_schema,
    update_provider_code_spec,
)

_example_schema = """\
resources:
- name: project
  provider_spec_attributes:
    - name: tags
      map:
        computed_optional_required: computed_optional
        element_type:
          string: {}
        description: Map that contains key-value pairs between 1 to 255 characters in length for tagging and categorizing the project. Maximum 50 tags
  schema:
    ignores:
      - pretty
      - envelope
      - links
      - tags
    attributes:
      aliases:
        groupId: id
  create:
    path: /api/atlas/v2/groups
    method: POST
  read:
    path: /api/atlas/v2/groups/{groupId}
    method: GET
  update:
    path: /api/atlas/v2/groups/{groupId}
    method: PATCH
  delete:
    path: /api/atlas/v2/groups/{groupId}
    method: DELETE
"""


def _default_schema(tmp_path: Path) -> PyTerraformSchema:
    schema_path = tmp_path / "terraform.yaml"
    schema_path.write_text(_example_schema)
    parsed = parse_py_terraform_schema(schema_path)
    return parsed


def test_parse_py_terraform_schema(tmp_path):
    parsed = _default_schema(tmp_path)
    assert parsed.resources
    project = parsed.resources[0]
    assert project.name == "project"
    project_dict = project.model_dump()
    assert project_dict["schema"]["ignores"] == ["pretty", "envelope", "links", "tags"]


_example_generator_config = """\
provider:
  name: mongodbatlas
resources:
  project:
    schema:
      ignores:
      - pretty
      - envelope
      - links
      - tags
      attributes:
        aliases:
          groupId: id
    create:
      path: /api/atlas/v2/groups
      method: POST
    read:
      path: /api/atlas/v2/groups/{groupId}
      method: GET
    update:
      path: /api/atlas/v2/groups/{groupId}
      method: PATCH
    delete:
      path: /api/atlas/v2/groups/{groupId}
      method: DELETE
"""


def test_dump_generator_config(tmp_path: Path):
    schema = _default_schema(tmp_path)
    assert _example_generator_config == dump_generator_config(schema)


EXAMPLE_PROVIDER_CODE_SPEC_PATH = (
    Path(__file__).parent / "test_data/provider-code-spec.json"
)


def test_update_provider_code_spec(tmp_path: Path):
    spec_before = parse_model(EXAMPLE_PROVIDER_CODE_SPEC_PATH, t=ProviderCodeSpec)

    original_names = [
        "cluster_count",
        "created",
        "id",
        "name",
        "org_id",
        "region_usage_restrictions",
        "with_default_alerts_settings",
    ]

    resource_name = "project"
    assert spec_before.resource_attribute_names(resource_name) == original_names
    schema = _default_schema(tmp_path)
    spec_after_str = update_provider_code_spec(schema, EXAMPLE_PROVIDER_CODE_SPEC_PATH)
    spec_after = parse_model(spec_after_str, t=ProviderCodeSpec, format="json")

    assert spec_after.resource_attribute_names(resource_name) == original_names + [
        "tags"
    ]
