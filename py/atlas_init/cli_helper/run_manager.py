import subprocess
import sys
import threading
from dataclasses import dataclass
from logging import Logger
from pathlib import Path
from tempfile import TemporaryDirectory

from zero_3rdparty.id_creator import simple_id


@dataclass
class ResultStore:
    result: str = ""
    exit_code: int | None = None


class ProcessManager:
    def __init__(self):
        self.processes = {}
        self.lock = threading.RLock()

    def __enter__(self):
        return self

    def run_process(self, command: str, cwd: Path, logger: Logger, env: dict | None = None, result_store: ResultStore | None = None) -> ResultStore:
        result_store = result_store or ResultStore()
        with TemporaryDirectory() as temp_dir:
            result_file = Path(temp_dir) / f"{simple_id()}.txt"
            with open(result_file, "w") as file:
                logger.info(f"running: '{command}' from '{cwd}'")
                with subprocess.Popen(
                    command.split(),
                    cwd=cwd,
                    env=env,
                    stdout=file,
                    stderr=sys.stderr,
                    stdin=sys.stdin,
                    start_new_session=True,
                ) as process:
                    with self.lock:
                        self.processes[threading.get_ident()] = process
                    try:
                        process.wait()
                    except KeyboardInterrupt:
                        process.terminate()
                        process.wait()
                    finally:
                        with self.lock:
                            del self.processes[threading.get_ident()]
                result_store.exit_code = process.returncode
            result_store.result = result_file.read_text()
        return result_store

    def __exit__(self, *_):
        self.terminate_all()

    def terminate_all(self):
        with self.lock:
            for process in self.processes.values():
                process.terminate()
