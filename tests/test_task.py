import pytest

from dashb.task import Task

import pytest
import time
import queue
import logging

# Suppress logging during tests
logging.getLogger().setLevel(logging.CRITICAL)


def test_task_runs_once():
    result_queue = queue.Queue()

    def simple_task():
        return "Success"

    def callback(result):
        result_queue.put(result)

    task = Task(simple_task, callback=callback)
    task.start()
    time.sleep(0.1)  # Give the task some time to execute

    assert result_queue.get(timeout=1) == "Success"


def test_task_periodic_execution():
    result_queue = queue.Queue()
    count = 0

    def periodic_task():
        nonlocal count
        count += 1
        return count

    def callback(result):
        result_queue.put(result)

    task = Task(periodic_task, callback=callback, interval=0.5)
    task.start()
    time.sleep(1.6)  # Wait for at least 3 intervals
    task.stop()

    assert result_queue.qsize() >= 3  # At least 3 executions


def test_task_handles_exceptions():
    result_queue = queue.Queue()

    def failing_task():
        raise ValueError("Test exception")

    def callback(result):
        result_queue.put(result)

    task = Task(failing_task, callback=callback)
    task.start()
    time.sleep(0.1)

    result = result_queue.get(timeout=1)
    assert isinstance(result, Exception)
    assert str(result) == "Test exception"


def test_task_respects_timeout():
    result_queue = queue.Queue()

    def slow_task():
        time.sleep(1)
        return "Completed"

    def callback(result):
        result_queue.put(result)

    task = Task(slow_task, callback=callback, interval=0.5)  # Timeout after 0.5 second
    task.start()
    time.sleep(0.5)  # Wait for at least 1 interval
    task.stop()

    assert (
        not result_queue.qsize()
    )  # Task should have timed out before returning a result


def test_task_skip_missed():
    result_queue = queue.Queue()

    def slow_task():
        time.sleep(0.6)
        return "Done"

    def callback(result):
        result_queue.put(result)

    task = Task(slow_task, callback=callback, interval=0.5, skip_missed=True)
    task.start()
    time.sleep(1.7)  # Wait for multiple intervals
    task.stop()

    assert result_queue.qsize() == 2  # Should skip some intervals but still run


def test_task_does_not_skip_missed():
    result_queue = queue.Queue()

    def slow_task():
        time.sleep(0.6)
        return "Done"

    def callback(result):
        result_queue.put(result)

    task = Task(slow_task, callback=callback, interval=0.5, skip_missed=False)
    task.start()
    time.sleep(1.9)
    task.stop()

    assert result_queue.qsize() >= 3  # Should execute sequentially without skipping


def test_task_stop():
    result_queue = queue.Queue()

    def simple_task():
        return "Running"

    def callback(result):
        result_queue.put(result)

    task = Task(simple_task, callback=callback, interval=0.5)
    task.start()
    time.sleep(1)
    task.stop()
    count = result_queue.qsize()

    time.sleep(1)  # Ensure task does not restart
    assert result_queue.qsize() == count  # Should not change after stopping


if __name__ == "__main__":
    pytest.main()
