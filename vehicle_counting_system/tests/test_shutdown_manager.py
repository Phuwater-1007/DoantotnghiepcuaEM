import unittest
import time
from unittest.mock import patch

from vehicle_counting_system.core.shutdown_manager import (
    ShutdownSnapshot,
    finalize_process_exit,
    has_lingering_runtime,
    run_cleanup_step,
)


class TestShutdownManager(unittest.TestCase):
    def test_run_cleanup_step_returns_true_when_action_finishes(self):
        calls = []

        def _action():
            calls.append("done")

        self.assertTrue(run_cleanup_step("quick action", _action, timeout=0.5))
        self.assertEqual(calls, ["done"])

    def test_run_cleanup_step_returns_false_on_timeout(self):
        def _slow_action():
            time.sleep(0.2)

        self.assertFalse(run_cleanup_step("slow action", _slow_action, timeout=0.01))

    def test_has_lingering_runtime_detects_threads_children_or_native_threads(self):
        self.assertFalse(
            has_lingering_runtime(
                ShutdownSnapshot(
                    python_threads=(),
                    child_pids=(),
                    os_thread_count=1,
                    rss_mb=123.0,
                )
            )
        )
        self.assertTrue(
            has_lingering_runtime(
                ShutdownSnapshot(
                    python_threads=("worker",),
                    child_pids=(),
                    os_thread_count=1,
                    rss_mb=123.0,
                )
            )
        )
        self.assertTrue(
            has_lingering_runtime(
                ShutdownSnapshot(
                    python_threads=(),
                    child_pids=(999,),
                    os_thread_count=1,
                    rss_mb=123.0,
                )
            )
        )
        self.assertTrue(
            has_lingering_runtime(
                ShutdownSnapshot(
                    python_threads=(),
                    child_pids=(),
                    os_thread_count=3,
                    rss_mb=123.0,
                )
            )
        )

    @patch("vehicle_counting_system.core.shutdown_manager.join_python_threads")
    @patch("vehicle_counting_system.core.shutdown_manager.terminate_child_processes")
    @patch("vehicle_counting_system.core.shutdown_manager.release_runtime_resources")
    @patch("vehicle_counting_system.core.shutdown_manager.log_shutdown_snapshot")
    def test_finalize_process_exit_returns_normally_when_runtime_is_clean(
        self,
        mock_log_snapshot,
        _mock_release_runtime_resources,
        _mock_terminate_children,
        _mock_join_threads,
    ):
        mock_log_snapshot.return_value = ShutdownSnapshot(
            python_threads=(),
            child_pids=(),
            os_thread_count=1,
            rss_mb=64.0,
        )

        self.assertEqual(finalize_process_exit(7, force_timeout=0.0), 7)


if __name__ == "__main__":
    unittest.main()
