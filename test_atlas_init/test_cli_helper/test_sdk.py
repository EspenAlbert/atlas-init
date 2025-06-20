import os
import re
from pathlib import Path

import pytest

from atlas_init.cli_helper.sdk import (
    BreakingChange,
    Change,
    find_breaking_changes,
    find_latest_sdk_version,
    format_breaking_changes,
    parse_breaking_changes,
    parse_line,
)
from atlas_init.repos.go_sdk import go_sdk_breaking_changes

example_lines = [
    (
        "- (*PushBasedLogExportApiService).CreatePushBasedLogConfiguration: changed from func(context.Context, string,*PushBasedLogExportProject) CreatePushBasedLogConfigurationApiRequest to func(context.Context, string, \\*CreatePushBasedLogExportProjectRequest) CreatePushBasedLogConfigurationApiRequest",
        "changed from",
        "PushBasedLogExportApiService",
        "CreatePushBasedLogConfiguration",
    ),
    (
        "- (\\*FederationIdentityProvider).GetAudienceClaimOk: removed",
        "removed",
        "FederationIdentityProvider",
        "GetAudienceClaimOk",
    ),
    (
        "- FederationIdentityProviderUpdate.AudienceClaim: removed",
        "removed",
        "FederationIdentityProviderUpdate",
        "AudienceClaim",
    ),
    ("LegacyBackupApi.DeleteLegacySnapshotExecute: added", None, None, None),
]


@pytest.mark.parametrize(
    "line,change,class_name,func_name",
    example_lines,
    ids=[line[-1] for line in example_lines],
)
def test_parse_changelog_lines(line, change, class_name, func_name):
    change_type_func_name = parse_line(line)
    if change is None:
        assert change_type_func_name is None
        return
    assert change_type_func_name is not None
    change_type, actual_class_name, actual_func_name = change_type_func_name
    assert change == change_type
    assert func_name == actual_func_name
    assert class_name == actual_class_name


@pytest.fixture
def sdk_path() -> Path:
    sdk_path = Path(os.environ["SDK_REPO_PATH"])
    assert sdk_path.exists(), f"not found {sdk_path}"
    return sdk_path


@pytest.mark.skip("manual test, needs go sdk directory")
def test_parse_breaking_changes(sdk_path):
    changes_dir = go_sdk_breaking_changes(sdk_path)
    changes1 = parse_breaking_changes(changes_dir)
    assert changes1
    for change, cls_name, name in sorted(changes1):
        print(f"change={change}, cls_name={cls_name}, name={name}")
        print(f"\t\tline={changes1[(change, cls_name, name)]}")  # type: ignore

    changes2 = parse_breaking_changes(changes_dir, start_sdk_version="v20231115007")
    assert changes2
    assert len(changes2) < len(changes1)


_example_code = """\
some_other_code := "Hello"
input: []admin20231115008.FederationIdentityProvider{
				{
					AssociatedDomains: &associatedDomains,
					AssociatedOrgs:    &associatedOrgs,
					DisplayName:       &displayName,
					IssuerUri:         &issuerURI,
					Id:                identityProviderID,
					Protocol:          &oidcProtocol,
					AudienceClaim:     &audienceClaim,
					ClientId:          &clientID,
					GroupsClaim:       &groupsClaim,
					RequestedScopes:   &requestedScopes,
					UserClaim:         &userClaim,
				},
			},

"""

_example_code_warning = """\
## v20231115009: - FederationIdentityProvider.AudienceClaim: removed
L002: 'FederationIdentityProvider' input: []admin20231115008.FederationIdentityProvider{
L010: 'AudienceClaim' \t\t\t\t\tAudienceClaim:     &audienceClaim,
"""


@pytest.mark.skipif(
    os.environ.get("GO_SDK_REL_PATH", "") == "",
    reason="needs os.environ[GO_SDK_REL_PATH]",
)
def test_find_breaking_changes(sdk_path):
    changes_dir = go_sdk_breaking_changes(sdk_path, os.environ["GO_SDK_REL_PATH"])
    changes1 = parse_breaking_changes(changes_dir)
    assert changes1

    found_changes = find_breaking_changes(_example_code, changes1)
    assert found_changes
    print(found_changes)
    change, breaking_change = found_changes.popitem()
    assert change == Change(
        change_type="removed",
        class_name="FederationIdentityProvider",
        func_name="AudienceClaim",
    )
    assert breaking_change == BreakingChange(
        version="v20231115009",
        line="- FederationIdentityProvider.AudienceClaim: removed",
    )
    assert format_breaking_changes(_example_code, {change: breaking_change}) == _example_code_warning


def test_find_latest_sdk_version():
    version = find_latest_sdk_version()
    assert re.match(r"v\d+", version)
