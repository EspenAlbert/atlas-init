import os

from atlas_init.cfn import get_last_cfn_type


def test_get_last_cfn_type():
    aws_profile = os.environ["AWS_PROFILE"]
    t = get_last_cfn_type("MongoDB::Atlas::Project", region="us-east-1", is_third_party=True)
    assert t
