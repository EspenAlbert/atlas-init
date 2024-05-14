import os

import pytest

from atlas_init.cli_cfn.cfn import get_last_cfn_type


@pytest.mark.skipif(os.environ.get("AWS_PROFILE", "") == "", reason="needs os.environ[AWS_PROFILE]")
def test_get_last_cfn_type():
    t = get_last_cfn_type("MongoDB::Atlas::Cluster", region="us-east-1", is_third_party=True)
    print(t)
    assert t
