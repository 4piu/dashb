import subprocess
import unittest
from unittest.mock import Mock, patch

from dashb.probe import gpu

NVIDIA = ({"index": 0, "name": "NVIDIA Test", "vendor": "nvidia", "provider": "nvml"},)
SMI_LINE = "0, 37, 1024, 16376, 45, 30.5, 320.00, [N/A], 210, 405\n"


def _smi_ok():
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=SMI_LINE, stderr="")


class GpuProbeTests(unittest.TestCase):
    def setUp(self):
        gpu._nvml_inited = False
        gpu._nvml_backoff = gpu._Backoff()
        gpu._smi_backoff = gpu._Backoff()
        gpu._smi_cache = None
        gpu._lhm_gpu_sensor_ids = {}
        patcher = patch.object(gpu, "_gpu_inventory", return_value=NVIDIA)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_subprocesses_are_hidden_and_time_limited(self):
        with patch.object(gpu.subprocess, "run", return_value=_smi_ok()) as run:
            gpu._run_hidden(["nvidia-smi", "-L"])
        kwargs = run.call_args.kwargs
        self.assertEqual(kwargs["creationflags"], gpu._NO_WINDOW_FLAGS)
        self.assertEqual(kwargs["timeout"], gpu.SMI_TIMEOUT_S)

    def test_nvml_device_name_accepts_str_and_bytes(self):
        self.assertEqual(gpu._as_str("RTX"), "RTX")
        self.assertEqual(gpu._as_str(b"RTX"), "RTX")

    def test_broken_nvml_does_not_spawn_nvidia_smi_per_sample(self):
        """Regression: after a driver upgrade NVML fails, and every metric sample
        used to launch its own (visible) nvidia-smi console window."""
        with (
            patch.object(gpu, "NVML_AVAILABLE", True),
            patch.object(gpu, "pynvml", create=True) as nvml,
            patch.object(gpu, "_run_hidden", return_value=_smi_ok()) as run,
        ):
            nvml.nvmlInit.side_effect = RuntimeError("Driver/library version mismatch")
            for _ in range(50):
                for field in gpu.GPU_FIELDS:
                    gpu.get_gpu_metric(field, 0)

            self.assertEqual(gpu.get_gpu_metric("temperature_c", 0), 45.0)
            self.assertEqual(gpu.get_gpu_metric("power_draw_w", 0), 30.5)
            self.assertEqual(
                gpu.get_gpu_metric("memory_used_bytes", 0), 1024 * 1024 * 1024
            )
            self.assertIsNone(gpu._smi_metric("fan_speed", 0))

        # NVML init is retried on a backoff, not per sample.
        nvml.nvmlInit.assert_called_once()
        # All fields come from one batched, cached nvidia-smi call.
        run.assert_called_once()

    def test_failing_nvidia_smi_backs_off(self):
        failed = subprocess.CompletedProcess(args=[], returncode=9, stdout="", stderr="")
        with (
            patch.object(gpu, "NVML_AVAILABLE", False),
            patch.object(gpu, "_run_hidden", return_value=failed) as run,
        ):
            for _ in range(100):
                gpu._smi_metric("utilization", 0)
        run.assert_called_once()

    def test_nvml_runtime_failure_drops_session_and_backs_off(self):
        nvml = Mock()
        nvml.NVML_ERROR_NOT_SUPPORTED = 3
        nvml.nvmlDeviceGetCount.side_effect = RuntimeError("GPU is lost")
        with (
            patch.object(gpu, "NVML_AVAILABLE", True),
            patch.object(gpu, "pynvml", nvml, create=True),
            patch.object(gpu, "_run_hidden", return_value=None),
        ):
            self.assertIsNone(gpu._nvml_metric("utilization", 0))
            self.assertFalse(gpu._nvml_inited)
            nvml.nvmlShutdown.assert_called_once()
            gpu._nvml_metric("utilization", 0)
        nvml.nvmlInit.assert_called_once()

    def test_unsupported_nvml_field_keeps_session_and_skips_smi(self):
        class NotSupported(Exception):
            value = 3

        nvml = Mock()
        nvml.NVML_ERROR_NOT_SUPPORTED = 3
        nvml.nvmlDeviceGetCount.return_value = 1
        nvml.nvmlDeviceGetFanSpeed.side_effect = NotSupported()
        with (
            patch.object(gpu, "NVML_AVAILABLE", True),
            patch.object(gpu, "pynvml", nvml, create=True),
            patch.object(gpu, "_run_hidden") as run,
        ):
            self.assertIsNone(gpu.get_gpu_metric("fan_speed", 0))
        self.assertTrue(gpu._nvml_inited)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
