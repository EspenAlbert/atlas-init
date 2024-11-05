import logging
from model_lib import dump, parse_payload
import pytest
from test_atlas_init.test_cli_tf.conftest import parse_resource_v3
from zero_3rdparty.dict_nested import iter_nested_key_values, pop_nested


logger = logging.getLogger(__name__)


def test_remove_nulls(tf_test_data_dir):
    for yml_path in (tf_test_data_dir / "tf_spec").glob("*.yml"):
        yaml_path = yml_path.with_name(yml_path.name.replace(".yml", ".yaml"))
        yaml_path.write_text(yml_path.read_text())
        parsed = parse_payload(yaml_path)
        assert isinstance(parsed, dict)
        keys_to_remove = []
        for key_path, value in iter_nested_key_values(
            parsed, include_list_indexes=True
        ):
            if value is None:
                keys_to_remove.append(key_path)
        logger.info(f"keys to remove: {keys_to_remove}")
        for key_path in keys_to_remove:
            pop_nested(parsed, key_path)
            new_yaml = dump(parsed, format="yaml")
        logger.info(f"dumping to {yaml_path}")
        yaml_path.write_text(new_yaml)


@pytest.mark.parametrize(
    "resource_name", ["searchdeployment", "pushbasedlogexport", "resourcepolicy"]
)
def test_parse_resource_schema_v3(spec_resources_v3_paths, resource_name):
    assert resource_name in spec_resources_v3_paths
    model = parse_resource_v3(spec_resources_v3_paths, resource_name)
    assert model
    assert model.schema
    assert model.schema.attributes
    attribute_names = [attr.name for attr in model.schema.attributes]
    assert attribute_names
    logger.info(f"attributes for {model.name}: {attribute_names}")
    nested_attributes = [
        attr.name for attr in model.schema.attributes if attr.is_nested
    ]
    logger.info(f"nested_attributes for {model.name}: {nested_attributes}")
