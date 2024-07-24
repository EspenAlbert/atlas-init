from __future__ import annotations

import json
import logging
import os
import sys
from pathlib import Path

from atlas_init.cli_helper.run import (
    run_binary_command_is_ok,
    run_command_receive_result,
)
from atlas_init.cli_tf.hcl.cluster_mig import (
    LEGACY_CLUSTER_TYPE,
    NEW_CLUSTER_TYPE,
    convert_clusters,
)
from atlas_init.cli_tf.hcl.parser import (
    ResourceBlock,
)

logger = logging.getLogger(__name__)


def should_continue(is_interactive: bool, question: str):
    for h in logger.handlers:
        h.flush()
    return input(f"{question} [y/N]") == "y" if is_interactive else True


def convert_and_validate(tf_dir: Path, *, is_interactive: bool = False):
    out_path = tf_dir / "conversion_cluster_adv_cluster.tf"
    new_clusters_path = convert_clusters(tf_dir, out_path)
    logger.info(f"found a total of {len(new_clusters_path)} clusters to convert and dumped them to {out_path}")
    if should_continue(is_interactive, "should import the new clusters?"):
        import_new_clusters(tf_dir, new_clusters_path)
        ensure_no_changes(tf_dir)
    else:
        logger.info("skipping import")
    if should_continue(is_interactive, "should replace the old cluster resources with the new ones?"):
        replace_old_clusters(tf_dir, out_path, new_clusters_path)
        logger.info("running plan to ensure there are no changes")
        ensure_no_changes(tf_dir)
        logger.info(f"migration successful, migrated {len(new_clusters_path)} clusters!")
    else:
        logger.info("skipping replacment")


def ensure_no_changes(tf_dir):
    assert run_binary_command_is_ok(
        "terraform", "plan -detailed-exitcode", tf_dir, logger
    ), "plan had error or changes, please check the output"


def import_new_clusters(tf_dir: Path, new_clusters_path: dict[tuple[Path, ResourceBlock], str]) -> None:
    current_state = run_command_receive_result("terraform show -json", tf_dir, logger)
    cluster_import_ids = read_cluster_import_ids(current_state)
    for path, block in new_clusters_path:
        import_id = cluster_import_ids.get(block.resource_id)
        assert import_id, f"no existing state for for {block.resource_id} @ {path}"
        new_resource_id = block.resource_id.replace(LEGACY_CLUSTER_TYPE, NEW_CLUSTER_TYPE)
        logger.info(f"importing {new_resource_id} with {import_id}")
        assert run_binary_command_is_ok(
            "terraform", f"import {new_resource_id} {import_id}", tf_dir, logger
        ), f"failed to import {new_resource_id}"


def replace_old_clusters(
    tf_dir: Path,
    out_path: Path,
    new_clusters_path: dict[tuple[Path, ResourceBlock], str],
) -> None:
    out_path.unlink()
    for (path, block), new_config in new_clusters_path.items():
        old_resource_id = block.resource_id
        logger.info(f"replacing {old_resource_id} @ {path}")
        old_text = path.read_text()
        new_text = old_text.replace(block.hcl, new_config)
        path.write_text(new_text)
        assert run_binary_command_is_ok(
            "terraform", f"state rm {old_resource_id}", tf_dir, logger
        ), f"failed to remove {old_resource_id}"


def read_cluster_import_ids(state: str) -> dict[str, str]:
    try:
        json_state = json.loads(state)
    except json.JSONDecodeError:
        logger.exception("unable to decode state")
        sys.exit(1)
    resources = json_state["values"]["root_module"]["resources"]
    assert isinstance(resources, list)
    import_ids = {}
    for resource in resources:
        if resource["type"] == LEGACY_CLUSTER_TYPE:
            project_id = resource["values"]["project_id"]
            name = resource["values"]["name"]
            import_ids[resource["address"]] = f"{project_id}-{name}"
    return import_ids


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    *_, tf_dir_str = sys.argv
    tf_dir_path = Path(tf_dir_str)
    assert tf_dir_path.is_dir(), f"not a directory: {tf_dir_path}"
    fast_forward = os.environ.get("FAST_FORWARD", "false").lower() in {
        "yes",
        "true",
        "1",
    }
    convert_and_validate(tf_dir_path, is_interactive=not fast_forward)
