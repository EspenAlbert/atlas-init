import logging
from concurrent.futures import ThreadPoolExecutor, wait
import time
from atlas_init.cli_helper.run_manager import ProcessManager, ResultStore

logger = logging.getLogger(__name__)

def test_terminate_on_exit(tmp_path):
    start = time.time()
    stores: list[ResultStore] = []
    with ThreadPoolExecutor(max_workers=4) as executor:
        with ProcessManager() as manager:
            futures = []
            # sourcery skip: no-loop-in-tests
            for i in range(4):
                store = ResultStore()
                stores.append(store)
                process_future = executor.submit(manager.run_process, f'echo {i}; sleep 10', logger=logger, cwd=tmp_path, result_store=store)
                futures.append(process_future)
            time.sleep(1)
        wait(futures, timeout=11)
    end = time.time()
    assert end - start < 2
    store_texts = [store.result for store in stores]
    assert store_texts == ['0; sleep 10\n', '1; sleep 10\n', '2; sleep 10\n', '3; sleep 10\n']
    assert [store.exit_code for store in stores] == [0, 0, 0, 0]
