import logging

from atlas_init.cli_helper.run import run_command_receive_result

logger = logging.getLogger(__name__)


def test_run_command_receive_result(tmp_path):
    result = "my-message"
    assert run_command_receive_result(f'echo {result}', tmp_path, logger) == result
