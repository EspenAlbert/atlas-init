import logging
import time
from concurrent.futures import wait

from atlas_init.cli_helper.run_manager import RunManager, ResultStore

logger = logging.getLogger(__name__)


def test_terminate_on_exit(tmp_path):
    start = time.time()
    stores: list[ResultStore] = []
    with RunManager() as manager:
        futures = []
        # sourcery skip: no-loop-in-tests
        for i in range(4):
            store = ResultStore()
            stores.append(store)
            process_future = manager.run_process(
                f"echo {i}; sleep 10", logger=logger, cwd=tmp_path, result_store=store
            )
            futures.append(process_future)
        time.sleep(0.2)
    wait(futures, timeout=11)
    end = time.time()
    assert end - start < 2
    store_texts = [store.result_str for store in stores]
    assert store_texts == ["0\n", "1\n", "2\n", "3\n"]
    assert [store.exit_code for store in stores] == [-2, -2, -2, -2]


def test_run_process_wait_on_log(tmp_path):
    with RunManager() as manager:
        store = ResultStore()
        future = manager.run_process_wait_on_log(
            'echo "hello"; sleep 10',
            logger=logger,
            cwd=tmp_path,
            result_store=store,
            line_in_log="hello",
            timeout=2,
        )
        assert store.in_progress()
    future.result()
    assert not store.in_progress()
    assert "hello" in store.result_str


def test_normal_wait(tmp_path):
    start = time.monotonic()
    with RunManager() as manager:
        result = manager.run_process(
            "echo hello; sleep 1", logger=logger, cwd=tmp_path
        ).result()
        assert result.exit_code == 0
    end = time.monotonic()
    assert end - start > 1.0


_python_script_log_after_terminate = """
import time
print("script started")
try:
    time.sleep(10)
    print("never interrupted!", flush=True)
    raise Exception("should not reach here")
except KeyboardInterrupt:
    print("KeyboardInterrupt", flush=True)
"""


def test_by_default_read_output_after_abort(tmp_path):
    python_script = tmp_path / "script.py"
    python_script.write_text(_python_script_log_after_terminate)
    with RunManager() as manager:
        future = manager.run_process_wait_on_log(
            "python ./script.py",
            logger=logger,
            cwd=tmp_path,
            line_in_log="script started",
            timeout=1,
        )
    time.sleep(0.3)
    result = future.result()
    assert "script started" in result.result_str
    assert "KeyboardInterrupt" in result.result_str


_python_script_never_terminate = """
import time
print("script started", flush=True)
try:
    time.sleep(10)
    raise Exception("should not reach here")
except KeyboardInterrupt:
    print("KeyboardInterrupt", flush=True)
    time.sleep(5)
    raise Exception("should have been killed by now")
"""


def test_kill_after_timeout(tmp_path):
    python_script = tmp_path / "script.py"
    python_script.write_text(_python_script_never_terminate)
    with RunManager() as manager:
        future = manager.run_process_wait_on_log(
            "python ./script.py",
            logger=logger,
            cwd=tmp_path,
            line_in_log="script started",
            timeout=1,
        )
    time.sleep(0.3)
    result = future.result()
    assert "script started" in result.result_str
    assert "KeyboardInterrupt" in result.result_str
    assert "should have been killed by now" not in result.result_str
