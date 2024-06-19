from pathlib import Path

from model_lib import dump

from atlas_init.cli_cfn.app import logger


def create_sample_file(
    samples_file: Path,
    log_group_name: str,
    resource_state: dict,
    prev_resource_state: dict | None = None,
):
    logger.info(f"adding sample @ {samples_file}")
    assert isinstance(resource_state, dict)
    new_json = dump(
        {
            "providerLogGroupName": log_group_name,
            "previousResourceState": prev_resource_state or {},
            "desiredResourceState": resource_state,
        },
        "json",
    )
    samples_file.write_text(new_json)
