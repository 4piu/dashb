import asyncio
import inspect
import logging
import queue
import threading
import time
from typing import Any, Callable, Optional


class Task:
    """
    A class that represents a periodic task with timeout handling.
    """

    def __init__(
        self,
        func: Callable,
        args: tuple = None,
        kwargs: dict = None,
        callback: Optional[Callable[[Any | Exception], Any]] = None,
        interval: int = None,
        skip_missed: bool = False,
    ):
        """
        Initializes a new Task instance.

        :param func: The function to be executed.
        :param args: Arguments to pass to the function.
        :param kwargs: Keyword arguments to pass to the function.
        :param callback: Callback function when task completes. Receives the return value of the task or exception.
        :param interval: Interval in seconds between executions. If None, task will run once.
        :param skip_missed: Skip missed executions if task took longer than interval, otherwise fire next run immediately.
        """
        self.func = func
        self.func_args = args or ()
        self.func_kwargs = kwargs or {}
        self.callback = callback
        self.interval = interval
        self.skip_missed = skip_missed

        self._daemon_thread = None
        self._task_thread = None
        self._stop_event = threading.Event()

    def _task(self, result: queue.Queue):
        """
        Runs the task function.
        """
        try:
            if inspect.iscoroutinefunction(self.func):  # async function
                result.put(asyncio.run(self.func(*self.func_args, **self.func_kwargs)))
            else:  # sync function
                result.put(self.func(*self.func_args, **self.func_kwargs))
        except Exception as e:
            result.put(e)
            logging.error(f"Task {self.func.__name__} failed: {e}")

    def _task_daemon(self):
        """
        A daemon function that runs the task at regular intervals.
        """
        while not self._stop_event.is_set():
            start_time = time.time()

            result = queue.Queue()

            self._task_thread = threading.Thread(target=self._task, args=(result,))
            self._task_thread.start()
            self._task_thread.join()

            if self._stop_event.is_set():
                break

            if self.callback:
                try:
                    if inspect.iscoroutinefunction(self.callback):  # async function
                        asyncio.run(self.callback(result.get_nowait()))
                    else:  # sync function
                        self.callback(result.get_nowait())
                except queue.Empty:
                    logging.error(f"Task {self.func.__name__} did not return a result")
                except Exception as e:
                    logging.error(f"Task {self.func.__name__} callback failed: {e}")

            if not self.interval:  # task runs only once
                break

            end_time = time.time()
            if end_time - start_time > self.interval:  # task took longer than interval
                logging.warning(
                    f"Task {self.func.__name__} took longer than interval: {end_time - start_time}s"
                )
                if self.skip_missed:  # wait until next closest interval
                    self._stop_event.wait(
                        max(0, self.interval - (end_time - start_time) % self.interval)
                    )
                else:  # fire next run immediately
                    continue
            else:
                self._stop_event.wait(max(0, self.interval - (end_time - start_time)))

    def start(self):
        """
        Runs the task function.
        """
        if self._daemon_thread and self._daemon_thread.is_alive():
            logging.warning(f"Task {self.func.__name__} is already running")
            return

        self._stop_event.clear()
        self._daemon_thread = threading.Thread(target=self._task_daemon, daemon=True)
        self._daemon_thread.start()

    def stop(self):
        """
        Stops the task function.
        """
        self._stop_event.set()

        if self._daemon_thread:
            self._daemon_thread.join()
        if self._task_thread and self._task_thread.is_alive():
            self._task_thread.join()

        logging.debug(f"Task {self.func.__name__} stopped")
