import logging
from collections import defaultdict
from atlas_init.tf_ext.args import TF_CLI_CONFIG_FILE_ARG
from atlas_init.tf_ext.settings import TfExtSettings
from atlas_init.tf_ext.provider_schema import ResourceSchema, parse_atlas_schema
from model_lib import dump, parse_model
from zero_3rdparty.file_utils import ensure_parents_write_text

logger = logging.getLogger(__name__)


def tf_desc_gen(
    tf_cli_config_file: str = TF_CLI_CONFIG_FILE_ARG,
):
    settings = TfExtSettings.from_env()
    out_path = settings.attribute_description_file_path
    resource_out_path = settings.attribute_resource_descriptions_file_path
    assert tf_cli_config_file
    schema = parse_atlas_schema()
    descriptions = {}
    descriptions_by_resource: dict[str, dict[str, str]] = defaultdict(dict)
    attr_desc_resource = {}

    def add_description(resource_type: str, attr_name: str, description: str | None) -> None:
        if not description:
            return
        descriptions_by_resource[resource_type][attr_name] = description
        if existing := descriptions.get(attr_name):
            if existing != description:
                old_resource_type = attr_desc_resource[attr_name]
                logger.info(
                    f"Descriptions differs between '{old_resource_type}' and '{resource_type}' for attribute '{attr_name}':\n{existing}\n{description}"
                )
                if len(existing) > len(description):
                    return
        descriptions[attr_name] = description
        attr_desc_resource[attr_name] = resource_type

    for resource_type, resource_schema in schema.raw_resource_schema.items():
        parsed_schema = parse_model(resource_schema, t=ResourceSchema)
        schema_block = parsed_schema.block
        for name, attribute in (schema_block.attributes or {}).items():
            add_description(resource_type, name, attribute.description)
        for name, block_type in (schema_block.block_types or {}).items():
            add_description(resource_type, name, block_type.description)
    descriptions_yaml = dump(dict(sorted(descriptions.items())), format="yaml")
    ensure_parents_write_text(out_path, descriptions_yaml)
    logger.info(f"Generated attribute descriptions to {out_path}")
    resource_descriptions_yaml = dump(
        {k: dict(sorted(v.items())) for k, v in sorted(descriptions_by_resource.items())}, format="yaml"
    )
    ensure_parents_write_text(resource_out_path, resource_descriptions_yaml)
    logger.info(f"Generated attribute resource descriptions to {resource_out_path}")
