from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from tempfile import TemporaryDirectory

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


def tf(cmd: str, tf_dir: Path, err_msg: str, err_msg_code_2: str = "") -> str:
    err_codes = {
        1: err_msg,
        2: err_msg_code_2,
    }
    with TemporaryDirectory() as temp_dir:
        result_file = Path(temp_dir) / "file"
        with open(result_file, "w") as file:
            exit_code = subprocess.call(
                f"terraform {cmd}".split(),
                stdin=sys.stdin,
                stderr=sys.stderr,
                stdout=file,
                cwd=tf_dir,
            )
            cmd_output = result_file.read_text().strip()
            if exit_code == 0:
                return cmd_output
            err_msg = err_codes.get(exit_code, err_msg) or err_msg
            logger.error(cmd_output)
            logger.error(err_msg)
            sys.exit(exit_code)


def convert_and_validate(tf_dir: Path, *, is_interactive: bool = False):
    out_path = tf_dir / "conversion_cluster_adv_cluster.tf"
    if out_path.exists() and should_continue(is_interactive, f"{out_path} already exists, should it be overwritten?"):
        logger.info(f"removing existing conversion file @ {out_path}")
        out_path.unlink()
    if adv_clusters := read_import_id_addresses(tf_dir, NEW_CLUSTER_TYPE):
        existing_addresses = ", ".join(adv_clusters.values())
        if should_continue(
            is_interactive,
            f"found existing advanced clusters: {existing_addresses}, should they be removed?",
        ):
            remove_from_state(tf_dir, adv_clusters.values())
    ensure_no_plan_changes(tf_dir)
    new_clusters_path = convert_clusters(tf_dir, out_path)
    logger.info(
        f"found a total of {len(new_clusters_path)} clusters to convert and generated their config to {out_path}"
    )
    if should_continue(is_interactive, f"should import the new clusters in {out_path}?"):
        import_new_clusters(tf_dir)
        ensure_no_plan_changes(tf_dir)
    else:
        logger.info("skipping import")
    if should_continue(is_interactive, "should replace the old cluster resources with the new ones?"):
        replace_old_clusters(tf_dir, out_path, new_clusters_path)
        ensure_no_plan_changes(tf_dir)
        logger.info(f"migration successful, migrated {len(new_clusters_path)} clusters!")
    else:
        logger.info("skipping replacment")


def remove_from_state(tf_dir, addresses: Iterable[str]) -> None:
    for address in addresses:
        logger.info(f"removing {address} from state")
        tf(f"state rm {address}", tf_dir, f"failed to remove {address}")


def ensure_no_plan_changes(tf_dir):
    logger.info("running plan to ensure there are no changes")
    tf(
        "plan -detailed-exitcode",
        tf_dir,
        "error running terraform plan",
        "plan had changes",
    )


def import_new_clusters(tf_dir: Path) -> None:
    cluster_import_ids = read_import_id_addresses(tf_dir)
    for import_id, resource_address in cluster_import_ids.items():
        new_resource_address = resource_address.replace(LEGACY_CLUSTER_TYPE, NEW_CLUSTER_TYPE)
        logger.info(f"importing {import_id} to {new_resource_address}")
        tf(
            f"import {new_resource_address} {import_id}",
            tf_dir,
            f"failed to import {new_resource_address}",
        )


def read_import_id_addresses(tf_dir: Path, resource_type: str = "") -> dict[str, str]:
    current_state = tf("show -json", tf_dir, "failed to read terraform state")
    return read_cluster_import_ids(current_state, resource_type)


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
    remove_from_state(tf_dir, read_import_id_addresses(tf_dir).values())


def read_cluster_import_ids(state: str, resource_type: str = "") -> dict[str, str]:
    resource_type = resource_type or LEGACY_CLUSTER_TYPE
    try:
        json_state = json.loads(state)
    except json.JSONDecodeError:
        logger.exception("unable to decode state")
        sys.exit(1)
    resources = json_state["values"]["root_module"]["resources"]
    assert isinstance(resources, list)
    import_ids = {}
    for resource in resources:
        if resource["type"] == resource_type:
            project_id = resource["values"]["project_id"]
            name = resource["values"]["name"]
            import_id = f"{project_id}-{name}"
            import_ids[import_id] = resource["address"]
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
