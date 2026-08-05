import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from dashb.probe.lhm import ElevatedLhmClient


class ElevatedLhmClientTests(unittest.TestCase):
    @patch("dashb.probe.lhm._free_loopback_port", return_value=12345)
    def test_failed_elevation_is_attempted_only_once(self, _free_port):
        client = ElevatedLhmClient(Path("helper.exe"))
        client._start_elevated_server = Mock()
        client._connect = Mock(return_value=False)

        with self.assertRaisesRegex(RuntimeError, "not accepted"):
            client._ensure_connection()
        with self.assertRaisesRegex(RuntimeError, "not accepted"):
            client._ensure_connection()

        client._start_elevated_server.assert_called_once_with()
        client._connect.assert_called_once()

    @patch("dashb.probe.lhm._free_loopback_port", return_value=12345)
    def test_launch_error_is_not_retried(self, _free_port):
        client = ElevatedLhmClient(Path("helper.exe"))
        client._start_elevated_server = Mock(side_effect=OSError("launch failed"))
        client._connect = Mock()

        for _attempt in range(2):
            with self.assertRaisesRegex(RuntimeError, "Could not start"):
                client._ensure_connection()

        client._start_elevated_server.assert_called_once_with()
        client._connect.assert_not_called()

    @patch("dashb.probe.lhm._free_loopback_port", return_value=12345)
    def test_stopped_helper_reconnects_but_never_relaunches(self, _free_port):
        client = ElevatedLhmClient(Path("helper.exe"))
        client._start_elevated_server = Mock()
        client._connect = Mock(side_effect=[True, False])

        client._ensure_connection()
        with self.assertRaisesRegex(RuntimeError, "helper stopped"):
            client._ensure_connection()
        with self.assertRaisesRegex(RuntimeError, "helper stopped"):
            client._ensure_connection()

        client._start_elevated_server.assert_called_once_with()
        self.assertEqual(client._connect.call_count, 2)

    @patch("dashb.probe.lhm._free_loopback_port", return_value=12345)
    def test_closed_client_cannot_launch_again(self, _free_port):
        client = ElevatedLhmClient(Path("helper.exe"))
        client._start_elevated_server = Mock()

        client.close()
        with self.assertRaisesRegex(RuntimeError, "client is closed"):
            client._ensure_connection()

        client._start_elevated_server.assert_not_called()


if __name__ == "__main__":
    unittest.main()
