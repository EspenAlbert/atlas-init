import logging
from atlas_init.repos.path import (
    find_resource_dirs,
    terraform_package_path,
    terraform_resource_test_names,
)

logger = logging.getLogger(__name__)


def test_non_resource_dirs(tf_repo_path):
    _, non_dirs = find_resource_dirs(terraform_package_path(tf_repo_path))
    assert sorted(non_dir.name for non_dir in non_dirs) == [
        "advancedclustertpf",
        "atlasuser",
        "controlplaneipaddresses",
        "flexrestorejob",
        "flexsnapshot",
        "projectipaddresses",
        "rolesorgid",
        "sharedtier",
    ]


def test_terraform_resource_test_names(tf_repo_path):
    tests = terraform_resource_test_names(tf_repo_path)
    assert tests
    logger.info(f"found {len(tests)} resources")
    for name, resource_tests in tests.items():
        logger.info(f"resource: {name}")
        for test_name in resource_tests:
            logger.info(f"  test: {test_name}")
