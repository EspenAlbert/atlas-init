import os

import pytest

from atlas_init.cli_root.trigger import create_realm_app


@pytest.mark.skipif(
    any(os.environ.get(name, "") == "" for name in ["MONGODB_ATLAS_PROJECT_ID", "MONGODB_ATLAS_CLUSTER_NAME"]),
    reason='needs env vars: ["MONGODB_ATLAS_PROJECT_ID", "MONGODB_ATLAS_CLUSTER_NAME"]),',
)
def test_manual_creation_of_service():
    create_realm_app()
