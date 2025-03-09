import pytest
from dashb.probe.gpu import get_nv_gpu_info
from unittest.mock import patch


@pytest.fixture
def mock_subprocess_run():
    with patch("dashb.probe.gpu.subprocess.run") as mock_run:
        yield mock_run


def test_get_nv_gpu_info_success(mock_subprocess_run):
    mock_subprocess_run.return_value.returncode = 0
    mock_subprocess_run.return_value.stdout = (
        b"Tesla K80, 50, 1024, 4096, 70, 100, 150, 875, 875, 875, 875, 2505, 2505\n"
    )

    result = get_nv_gpu_info()

    expected_result = [
        "Tesla K80",
        50.0,
        1024.0,
        4096.0,
        70.0,
        100.0,
        150.0,
        875.0,
        875.0,
        875.0,
        875.0,
        2505.0,
        2505.0,
    ]

    assert result == expected_result


def test_get_nv_gpu_info_failure(mock_subprocess_run):
    mock_subprocess_run.return_value.returncode = 1

    result = get_nv_gpu_info()

    assert result == []


def test_get_nv_gpu_info_invalid_output(mock_subprocess_run):
    mock_subprocess_run.return_value.returncode = 0
    mock_subprocess_run.return_value.stdout = b"Invalid Output\n"

    result = get_nv_gpu_info()

    assert result == []


if __name__ == "__main__":
    pytest.main()
