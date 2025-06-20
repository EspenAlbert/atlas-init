from pathlib import Path

from model_lib import parse_model

from atlas_init.cli_tf.schema import (
    ChangeAttributeType,
    ComputedOptionalRequired,
    IgnoreNested,
    ProviderCodeSpec,
    PyTerraformSchema,
    RenameAttribute,
    SkipValidators,
    TFResource,
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
data_sources: {}
"""


def test_dump_generator_config(tmp_path: Path):
    schema = _default_schema(tmp_path)
    assert _example_generator_config == dump_generator_config(schema)


EXAMPLE_PROVIDER_CODE_SPEC_PATH = Path(__file__).parent / "test_data/provider-code-spec.json"


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
    assert spec_before.attribute_names(resource_name) == original_names
    schema = _default_schema(tmp_path)
    spec_after_str = update_provider_code_spec(schema, EXAMPLE_PROVIDER_CODE_SPEC_PATH)
    spec_after = parse_model(spec_after_str, t=ProviderCodeSpec, format="json")

    assert spec_after.attribute_names(resource_name) == original_names + ["tags"]


def resource_provider_code_spec(name: str) -> Path:
    default_name = EXAMPLE_PROVIDER_CODE_SPEC_PATH.name
    return EXAMPLE_PROVIDER_CODE_SPEC_PATH.with_name(default_name.replace(".json", f"-{name}.json"))


def test_update_provider_code_spec_stream_processor():
    resource_name = "streamprocessor"
    spec = resource_provider_code_spec(resource_name)
    ignore_links = IgnoreNested(path="*.links")
    assert ignore_links.use_wildcard
    rename_id = RenameAttribute(from_name="_id", to_name="processor_id")
    change_attribute_type = ChangeAttributeType(path="processor_name", new_value=ComputedOptionalRequired.REQUIRED)
    skip_validators = SkipValidators()
    schema = PyTerraformSchema(
        resources=[
            TFResource(
                name=resource_name,
                extensions=[
                    ignore_links,
                    rename_id,
                    change_attribute_type,
                    skip_validators,
                ],
            )
        ]
    )
    spec_after_str = update_provider_code_spec(schema, spec)
    spec_after = parse_model(spec_after_str, t=ProviderCodeSpec, format="json")
    assert spec_after
    assert '"name":"links",' not in spec_after_str
    assert '"name":"_id",' not in spec_after_str
    assert '"validators":' not in spec_after_str
    processor_name_after = spec_after.read_attribute(resource_name, "processor_name")
    assert change_attribute_type.read_value(processor_name_after) == "required"
    all_attribute_paths = sorted((path, name) for path, name, _ in spec_after.iter_all_attributes(resource_name))
    assert all_attribute_paths == [
        ("coll", "[1].single_nested.attributes.[0].single_nested.attributes.[0]"),
        (
            "connection_name",
            "[1].single_nested.attributes.[0].single_nested.attributes.[1]",
        ),
        ("db", "[1].single_nested.attributes.[0].single_nested.attributes.[2]"),
        ("dlq", "[1].single_nested.attributes.[0]"),
        ("instance_name", ""),
        ("name", ""),
        ("options", ""),
        ("pipeline", ""),
        ("processor_id", ""),
        ("processor_name", ""),
        ("project_id", ""),
        ("state", ""),
        ("stats", ""),
    ]
