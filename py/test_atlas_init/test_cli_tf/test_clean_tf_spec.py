import logging
from pathlib import Path

import pytest
from model_lib import dump, parse_payload
from zero_3rdparty.dict_nested import iter_nested_key_values, pop_nested

logger = logging.getLogger(__name__)


def remove_nulls_and_nested(yaml_path: Path):
    parsed = parse_payload(yaml_path)
    assert isinstance(parsed, dict)
    keys_to_remove = [
        key_path
        for key_path, value in iter_nested_key_values(parsed, include_list_indexes=True)
        if value is None or key_path.endswith(".links")
    ]
    logger.info(f"keys to remove: {keys_to_remove}")
    new_yaml = None
    for key_path in keys_to_remove:
        pop_nested(parsed, key_path)
        new_yaml = dump(parsed, format="yaml")
    if new_yaml:
        logger.info(f"dumping to {yaml_path}")
        yaml_path.write_text(new_yaml)


@pytest.mark.parametrize(
    "resource_name",
    ["searchdeployment", "pushbasedlogexport", "resourcepolicy", "advancedcluster"],
)
def test_parse_resource_schema_v3(parse_resource_v3, resource_name):
    model = parse_resource_v3(resource_name)
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


# generated_name_wrong --> generated_name_correct
# also, remember to update: _sdk_attribute_aliases
name_aliases = {
    "mongo_dbemployee_access_grant": "mongo_db_employee_access_grant",
    "mongo_dbmajor_version": "mongo_db_major_version",
    "mongo_dbversion": "mongo_db_version",
}


def test_post_process_specs(spec_resources_v3_paths):
    for (
        resource_name,
        spec_path,
    ) in spec_resources_v3_paths.items():  # sourcery skip: no-loop-in-tests
        remove_nulls_and_nested(spec_path)
        new_text = spec_path.read_text()
        for (
            old_name,
            new_name,
        ) in name_aliases.items():  # sourcery skip: no-loop-in-tests
            if old_name in new_text:  # sourcery skip: no-conditionals-in-tests
                logger.info(f"replacing {old_name} with {new_name} in {resource_name}")
                new_text = new_text.replace(old_name, new_name)
        spec_path.write_text(new_text)
