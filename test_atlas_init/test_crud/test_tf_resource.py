from datetime import timedelta
from zero_3rdparty.datetime_utils import utc_now
from atlas_init.cli_tf.go_test_run import GoTestRun
from atlas_init.cli_tf.go_test_tf_error import GoTestDefaultError, GoTestError, GoTestErrorClass
from atlas_init.crud.mongo_dao import (
    read_tf_error_by_run,
    read_tf_errors,
    store_or_update_tf_errors,
)


def test_tf_errors(settings, subtests):
    now = utc_now()
    run1 = GoTestRun(name="test_run1", ts=now)
    run2 = GoTestRun(name="test_run1", ts=now + timedelta(days=1))
    error1 = GoTestError(
        details=GoTestDefaultError(error_str="This is a test error"),
        run=run1,
    )
    error2 = GoTestError(
        details=GoTestDefaultError(error_str="This is a test error"),
        run=run2,
    )
    with subtests.test("empty errors behavior"):
        empty = read_tf_errors(settings)
        assert empty.errors == []
        assert empty.classified_errors() == []
        assert empty.look_for_existing_classifications(error1) is None
    with subtests.test("store and read errors"):
        store_or_update_tf_errors(settings, [error1])
    with subtests.test("read error by run"):
        error_back = read_tf_error_by_run(settings, run1)
        assert error_back == error1
    with subtests.test("add 2nd error should keep the first one"):
        store_or_update_tf_errors(settings, [error2])
        errors = read_tf_errors(settings)
        assert len(errors.errors) == 2
        assert errors.errors[0] == error1
        assert errors.errors[1] == error2
        assert errors.classified_errors() == []
    with subtests.test("update error with classification"):
        error1.human_error_class = GoTestErrorClass.FLAKY_400
        error1.bot_error_class = GoTestErrorClass.FLAKY_400
        store_or_update_tf_errors(settings, [error1])
        errors = read_tf_errors(settings)
        assert len(errors.errors) == 2
        assert errors.errors[0] == error1
        assert errors.classified_errors() == [error1]
        assert errors.look_for_existing_classifications(error1) == (
            GoTestErrorClass.FLAKY_400,
            GoTestErrorClass.FLAKY_400,
        )
