import pytest
from ask_shell.ask import question_patcher
from ask_shell.settings import AskShellSettings
from zero_3rdparty.datetime_utils import utc_now

from atlas_init.cli_tf.ci_tests import ask_user_to_classify_error
from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.cli_tf.go_test_tf_error import (
    ErrorClassAuthor,
    GoTestDefaultError,
    GoTestErrorClass,
    GoTestErrorClassification,
)


def test_ask_user_to_classify_error(tmp_path):
    pytest.skip("some problem with Input is not a terminal now it seems")
    with question_patcher(settings=AskShellSettings.for_testing(tmp_path), responses=[""]):
        run = GoTestRun(name="test_run", ts=utc_now())
        cls = GoTestErrorClassification(
            details=GoTestDefaultError(
                error_str="This is a test error",
            ),
            run_id=run.id,
            author=ErrorClassAuthor.LLM,
            test_name="test_name",
            error_class=GoTestErrorClass.FLAKY_400,
        )
        assert ask_user_to_classify_error(cls, run) == GoTestErrorClass.FLAKY_400
