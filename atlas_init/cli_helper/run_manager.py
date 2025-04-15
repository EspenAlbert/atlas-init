from __future__ import annotations

import logging
import os
import signal
import subprocess  # nosec
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from logging import Logger
from pathlib import Path
from time import monotonic

from atlas_init.cli_helper.run import LOG_CMD_PREFIX, find_binary_on_path

default_logger = logging.getLogger(__name__)


class ResultInProgressError(Exception):
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
    _recent_lines: deque = field(default_factory=lambda: deque(maxlen=1000))

    result: list[str] = field(default_factory=list)
    exit_code: int | None = None
    _aborted: bool = False
    _terminated: bool = False
    _killed: bool = False

    @property
    def result_str(self) -> str:
        return "".join(self.result)

    @property
    def is_ok(self) -> bool:
        if self.in_progress():
            raise ResultInProgressError
        return self.exit_code == 0

    def _add_line(self, line: str) -> None:
        self._recent_lines.append(line)
        self.result.append(line)

    def unexpected_error(self) -> bool:
        if self.in_progress():
            raise ResultInProgressError
        return self.exit_code != 0 and not self._aborted

    def force_stopped(self) -> bool:
        if self.in_progress():
            raise ResultInProgressError
        return self._killed or self._terminated

    def in_progress(self) -> bool:
        return self.exit_code is None

    def wait(self) -> None:
        condition = self.wait_condition
        if not condition:
            return
        timeout = condition.timeout
        start = monotonic()
        while monotonic() - start < timeout:
            if not self.in_progress():
                raise LogTextNotFoundError(self)
            while self._recent_lines:
                line = self._recent_lines.popleft()
                if condition.line in line:
                    return
            time.sleep(0.1)
        raise LogTextNotFoundError(self)

    def _abort(self) -> None:
        self._aborted = True

    def _terminate(self) -> None:
        self._terminated = True

    def _kill(self) -> None:
        self._killed = True


class RunManager:
    def __init__(
        self,
        worker_count: int = 100,
        signal_int_timeout_s: float = 0.2,
        signal_term_timeout_s: float = 0.2,
        signal_kill_timeout_s: float = 0.2,
        *,
        dry_run: bool = False,
    ):
        """
        Args:
            worker_count: the number of workers to run in parallel
            terminate_read_timeout: the time to wait after terminating a process before closing the output
        """
        self.processes: dict[int, subprocess.Popen] = {}
        self.results: dict[int, ResultStore] = {}
        self.lock = threading.RLock()
        self.pool = ThreadPoolExecutor(max_workers=worker_count)
        self.signal_int_timeout_s = signal_int_timeout_s
        self.signal_term_timeout_s = signal_term_timeout_s
        self.signal_kill_timeout_s = signal_kill_timeout_s
        self.dry_run = dry_run

    def set_timeouts(self, timeout: float):
        self.signal_int_timeout_s = timeout
        self.signal_term_timeout_s = timeout
        self.signal_kill_timeout_s = timeout

    def __enter__(self):
        self.pool.__enter__()
        return self

    def run_process_wait_on_log(
        self,
        command: str,
        cwd: Path,
        logger: Logger | None,
        env: dict | None = None,
        result_store: ResultStore | None = None,
        *,
        line_in_log: str,
        timeout: float,
        binary: str = "",
    ) -> Future[ResultStore]:
        command = self._resolve_command(binary, command, logger)
        store = result_store or ResultStore()
        store.wait_condition = WaitOnText(line=line_in_log, timeout=timeout)
        future = self.pool.submit(self._run, command, cwd, logger, env, store)
        if not self.dry_run:
            store.wait()
        return future

    def run_process(
        self,
        command: str,
        cwd: Path,
        logger: Logger | None,
        env: dict | None = None,
        result_store: ResultStore | None = None,
        *,
        binary: str = "",
    ) -> Future[ResultStore]:
        command = self._resolve_command(binary, command, logger)
        return self.pool.submit(self._run, command, cwd, logger, env, result_store)

    def _resolve_command(self, binary: str, command: str, logger: Logger | None):
        if binary:
            binary_path = find_binary_on_path(binary, logger or default_logger, allow_missing=self.dry_run)
            command = f"{binary_path} {command}"
        return command

    def _run(
        self,
        command: str,
        cwd: Path,
        logger: Logger | None,
        env: dict | None = None,
        result: ResultStore | None = None,
    ) -> ResultStore:
        result = result or ResultStore()
        logger = logger or default_logger

        def read_output(process: subprocess.Popen):
            for line in process.stdout:  # type: ignore
                result._add_line(line)

        sys_stderr = sys.stderr

        def read_stderr(process: subprocess.Popen):
            for line in process.stderr:  # type: ignore
                sys_stderr.write(line)
                result._add_line(line)

        logger.info(f"{LOG_CMD_PREFIX}{command}' from '{cwd}'")
        if self.dry_run:
            result.exit_code = 0
            result.result.append(f"DRY RUN: {command}")
            return result
        with subprocess.Popen(
            command,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=sys.stdin,
            start_new_session=True,
            shell=True,  # noqa: S602 # We control the calls to this function and don't suspect any shell injection #nosec
            bufsize=0,
            text=True,  # This makes it return strings instead of bytes
        ) as process:
            with self.lock:
                self.processes[threading.get_ident()] = process
                self.results[threading.get_ident()] = result
            read_future_out = self.pool.submit(read_output, process)
            read_future_err = self.pool.submit(read_stderr, process)
            try:
                process.wait()
            except Exception:
                logger.exception(f"failed to run command: {command}")
            finally:
                for std_name, future in zip(["stdout", "stderr"], [read_future_out, read_future_err], strict=False):
                    try:
                        future.result(1)
                    except BaseException:
                        logger.exception(f"failed to read output ({std_name}) for command: {command}")
                with self.lock:
                    del self.processes[threading.get_ident()]
                    del self.results[threading.get_ident()]
        result.exit_code = process.returncode
        if result.unexpected_error():
            logger.error(f"command failed '{command}', error code: {result.exit_code}")
        if result.force_stopped():
            logger.error(f"command killed '{command}'")
        return result

    def __exit__(self, *_):
        self.pool.shutdown(wait=False, cancel_futures=True)  # wait happens in __exit__, avoid new futures starting
        self.terminate_all()
        self.pool.__exit__(None, None, None)

    def terminate_all(self):
        self._send_signal_to_all(signal.SIGINT, ResultStore._abort)
        self.wait_for_processes_ok(self.signal_int_timeout_s)
        self._send_signal_to_all(signal.SIGTERM, ResultStore._terminate)
        self.wait_for_processes_ok(self.signal_term_timeout_s)
        self._send_signal_to_all(signal.SIGKILL, ResultStore._kill)
        self.wait_for_processes_ok(self.signal_kill_timeout_s)

    def _send_signal_to_all(self, signal_type: signal.Signals, result_call: Callable[[ResultStore], None]):
        with self.lock:
            for pid, process in self.processes.items():
                result_call(self.results[pid])
                gpid = os.getpgid(process.pid)
                os.killpg(gpid, signal_type)

    def wait_for_processes_ok(self, timeout: float):
        start = monotonic()
        if not self.processes:
            return True
        while monotonic() - start < timeout:
            with self.lock:
                if not any(result.in_progress() for result in self.results.values()):
                    return True
            time.sleep(0.1)
        return False
