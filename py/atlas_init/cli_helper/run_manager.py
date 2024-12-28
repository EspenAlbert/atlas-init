from __future__ import annotations

import logging
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from logging import Logger
from pathlib import Path
from time import monotonic

default_logger = logging.getLogger(__name__)


class ResultInPrgoressError(Exception):
    pass


class ResultDoneError(Exception):
    pass


class LogTextNotFoundError(Exception):
    def __init__(self, store: ResultStore) -> None:
        self.store = store
        super().__init__(store)


@dataclass
class WaitOnText:
    line: str
    timeout: float


@dataclass
class ResultStore:
    wait_condition: WaitOnText | None = None

    result: list[str] = field(default_factory=list)
    exit_code: int | None = None
    _aborted: bool = False
    _killed: bool = False

    @property
    def result_str(self) -> str:
        return "".join(self.result)

    @property
    def is_ok(self) -> bool:
        if self.in_progress():
            raise ResultInPrgoressError
        return self.exit_code == 0

    def unexpected_error(self) -> bool:
        if self.in_progress():
            raise ResultInPrgoressError
        return self.exit_code != 0 and not self._aborted

    def got_killed(self) -> bool:
        if self.in_progress():
            raise ResultInPrgoressError
        return self._killed

    def in_progress(self) -> bool:
        return self.exit_code is None

    def _add_line(self, line: str) -> None:
        self.result.append(line)

    def wait(self) -> None:
        condition = self.wait_condition
        if not condition:
            return
        timeout = condition.timeout
        start = monotonic()
        look_index = 0
        while monotonic() - start < timeout:
            if not self.in_progress():
                raise LogTextNotFoundError(self)
            for line in self.result[look_index:]:
                look_index += 1
                if condition.line in line:
                    return
            time.sleep(0.1)
        raise LogTextNotFoundError(self)

    def _abort(self) -> None:
        self._aborted = True

    def _kill(self) -> None:
        self._killed = True


class ProcessManager:
    def __init__(self, worker_count: int = 100, terminate_read_timeout: float = 0.2, terminate_abort_timeout: float = 0.2):
        """
        Args:
            worker_count: the number of workers to run in parallel
            terminate_read_timeout: the time to wait after terminating a process before closing the output
        """
        self.processes: dict[int, subprocess.Popen] = {}
        self.results: dict[int, ResultStore] = {}
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=worker_count)
        self.terminate_read_timeout = terminate_read_timeout
        self.terminate_abort_timeout = terminate_abort_timeout

    def __enter__(self):
        self.pool.__enter__()
        return self

    def run_process_wait_on_log(
        self,
        command: str,
        cwd: Path,
        logger: Logger,
        env: dict | None = None,
        result_store: ResultStore | None = None,
        *,
        line_in_log: str,
        timeout: float,
    ) -> Future[ResultStore]:
        store = result_store or ResultStore()
        store.wait_condition = WaitOnText(line=line_in_log, timeout=timeout)
        future = self.pool.submit(self._run, command, cwd, logger, env, store)
        store.wait()
        return future

    def run_process(
        self,
        command: str,
        cwd: Path,
        logger: Logger,
        env: dict | None = None,
        result_store: ResultStore | None = None,
    ) -> Future[ResultStore]:
        return self.pool.submit(self._run, command, cwd, logger, env, result_store)

    def _run(
        self,
        command: str,
        cwd: Path,
        logger: Logger,
        env: dict | None = None,
        result: ResultStore | None = None,
    ) -> ResultStore:
        result = result or ResultStore()
        with subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=sys.stderr,
            stdin=sys.stdin,
            start_new_session=True,
            shell=True,  # noqa: S602 # We control the calls to this function and don't suspect any shell injection
            bufsize=0,
            text=True,  # This makes it return strings instead of bytes
        ) as process:
            with self.lock:
                self.processes[threading.get_ident()] = process
                self.results[threading.get_ident()] = result
            try:
                for line in process.stdout:  # type: ignore
                    result._add_line(line) # noqa: SLF001 # private call ok within the same file
                process.wait()
            except KeyboardInterrupt:
                process.terminate()
                process.wait()
            finally:
                with self.lock:
                    del self.processes[threading.get_ident()]
                    del self.results[threading.get_ident()]
        result.exit_code = process.returncode
        if result.unexpected_error():
            logger.error(f"command failed '{command}', error code: {result.exit_code}")
        if result.got_killed():
            logger.error(f"command killed '{command}'")
        return result

    def __exit__(self, *_):
        self.pool.shutdown(
            wait=False, cancel_futures=True
        )  # wait happens in __exit__, avoid new futures starting
        self.terminate_all()
        self.pool.__exit__(None, None, None)

    def terminate_all(self):
        with self.lock:
            processes = self.processes
            if not processes:
                return
            for pid, process in processes.items():
                self.results[pid]._abort() # noqa: SLF001 # private call ok within the same file
                gpid = os.getpgid(process.pid)
                os.killpg(gpid, signal.SIGINT) # use process group to send to all children
        time.sleep(self.terminate_read_timeout)
        with self.lock:
            for process in self.processes.values():
                process.stdout.close()  # type: ignore
        self._sleep_until_done(self.terminate_abort_timeout)
        with self.lock:
            for pid, process in self.processes.items():
                result = self.results[pid]
                if result.in_progress():
                    result._kill() # noqa: SLF001 # private call ok within the same file
                    process.kill()

    def _sleep_until_done(self, seconds: float):
        start = monotonic()
        while monotonic() - start < seconds:
            time.sleep(0.1)
            if not self.processes:
                return
