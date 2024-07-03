from datetime import timedelta
import os
import pytest
from zero_3rdparty.datetime_utils import utc_now
from atlas_init.cli_tf.github_logs import GH_TOKEN_ENV_NAME, REQUIRED_GH_ENV_VARS, print_log_failures


@pytest.mark.skipif(
    any(os.environ.get(name, "") == "" for name in REQUIRED_GH_ENV_VARS),
    reason=f'needs env vars: {REQUIRED_GH_ENV_VARS}',
)
def test_print_log_failures():
    print_log_failures(utc_now() - timedelta(days=7))