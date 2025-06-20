from zero_3rdparty.datetime_utils import utc_now

from ask_shell.interactive import question_patcher
from atlas_init.cli_tf.ci_tests import ask_user_to_classify_error
from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.cli_tf.go_test_tf_error import (
    ErrorClassAuthor,
    GoTestDefaultError,
    GoTestErrorClass,
    GoTestErrorClassification,
)


def test_ask_user_to_classify_error():
    with question_patcher([""]):
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
