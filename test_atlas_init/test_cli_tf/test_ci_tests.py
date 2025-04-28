from zero_3rdparty.datetime_utils import utc_now


from atlas_init.cli_tf.ci_tests import ask_user_to_classify_error
from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.cli_tf.go_test_tf_error import GoTestDefaultError, GoTestError, GoTestErrorClass
from atlas_init.settings.interactive2 import question_patcher

def test_ask_user_to_classify_error():
    with question_patcher([""]):
        error = GoTestError(
            details=GoTestDefaultError(
                error_str="This is a test error",
            ),
            run=GoTestRun(name="test_run", ts=utc_now()),
            bot_error_class=GoTestErrorClass.FLAKY_400,
        )
        assert ask_user_to_classify_error(error) == GoTestErrorClass.FLAKY_400
