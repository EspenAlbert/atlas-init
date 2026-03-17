import pytest

from atlas_init.cli_cfn.aws import deactivate_third_party_type, deregister_cfn_resource_type


TYPE_NAME = "MongoDB::Atlas::AlertConfiguration"
REGION = "me-central-1"


@pytest.mark.manual
def test_deregister_alert_configuration():
    result = deregister_cfn_resource_type(TYPE_NAME, deregister=True, region_filter=REGION)
    assert result is None or result.type_name == TYPE_NAME

@pytest.mark.manual
def test_deactivate_alert_configuration_dry_run():
    deactivate_third_party_type(TYPE_NAME, REGION, dry_run=False)


@pytest.mark.manual
def test_deactivate_alert_configuration():
    result = deactivate_third_party_type(TYPE_NAME, REGION)
    assert result is None or result.type_name == TYPE_NAME
