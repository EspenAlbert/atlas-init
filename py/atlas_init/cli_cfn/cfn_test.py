import os

from atlas_init.cli_cfn.cfn import get_last_cfn_type


def test_get_last_cfn_type():
    aws_profile = os.environ["AWS_PROFILE"]
    t = get_last_cfn_type("MongoDB::Atlas::Cluster", region="us-east-1", is_third_party=True)
    print(t)
    assert t
