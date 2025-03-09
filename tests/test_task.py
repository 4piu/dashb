import pytest

from dashb.task import Task

import pytest
import time
import queue
import logging
import asyncio

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


@pytest.mark.asyncio
async def test_async_task():
    result_queue = queue.Queue()

    async def async_task():
        await asyncio.sleep(0.1)
        return "Async Success"

    def callback(result):
        result_queue.put(result)

    task = Task(async_task, callback=callback)
    task.start()
    await asyncio.sleep(0.2)  # Give the task some time to execute

    assert result_queue.get(timeout=1) == "Async Success"


@pytest.mark.asyncio
async def test_async_callback():
    result_queue = queue.Queue()

    def simple_task():
        return "Success"

    async def async_callback(result):
        await asyncio.sleep(0.1)
        result_queue.put(result)

    task = Task(simple_task, callback=async_callback)
    task.start()
    await asyncio.sleep(0.2)  # Give the task some time to execute

    assert result_queue.get(timeout=1) == "Success"


@pytest.mark.asyncio
async def test_async_task_and_callback():
    result_queue = queue.Queue()

    async def async_task():
        await asyncio.sleep(0.1)
        return "Async Success"

    async def async_callback(result):
        await asyncio.sleep(0.1)
        result_queue.put(result)

    task = Task(async_task, callback=async_callback)
    task.start()
    await asyncio.sleep(0.3)  # Give the task some time to execute

    assert result_queue.get(timeout=1) == "Async Success"


def test_multiple_tasks_running_simultaneously():
    result_queue_1 = queue.Queue()
    result_queue_2 = queue.Queue()

    def task_1():
        return "Task 1 Completed"

    def task_2():
        return "Task 2 Completed"

    def callback_1(result):
        result_queue_1.put(result)

    def callback_2(result):
        result_queue_2.put(result)

    task1 = Task(task_1, callback=callback_1)
    task2 = Task(task_2, callback=callback_2)

    task1.start()
    task2.start()

    time.sleep(0.2)  # Give tasks some time to execute

    assert result_queue_1.get(timeout=1) == "Task 1 Completed"
    assert result_queue_2.get(timeout=1) == "Task 2 Completed"


@pytest.mark.asyncio
async def test_multiple_async_tasks_and_callbacks():
    result_queue_1 = queue.Queue()
    result_queue_2 = queue.Queue()

    async def async_task_1():
        await asyncio.sleep(0.1)
        return "Async Task 1 Completed"

    async def async_task_2():
        await asyncio.sleep(0.2)
        return "Async Task 2 Completed"

    async def async_callback_1(result):
        await asyncio.sleep(0.1)
        result_queue_1.put(result)

    async def async_callback_2(result):
        await asyncio.sleep(0.1)
        result_queue_2.put(result)

    task1 = Task(async_task_1, callback=async_callback_1)
    task2 = Task(async_task_2, callback=async_callback_2)

    task1.start()
    task2.start()

    await asyncio.sleep(0.5)  # Give tasks some time to execute

    assert result_queue_1.get(timeout=1) == "Async Task 1 Completed"
    assert result_queue_2.get(timeout=1) == "Async Task 2 Completed"


if __name__ == "__main__":
    pytest.main()
