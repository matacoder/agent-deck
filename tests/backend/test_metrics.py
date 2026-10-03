from io import StringIO
from unittest.mock import patch

from support import PanelCase


class MetricsTests(PanelCase):
    def test_cpu_interval_excludes_guest_and_ram_excludes_available(self):
        stats = iter(["cpu 100 0 100 800 0 0 0 0 20 0\n",
                      "cpu 130 0 120 850 0 0 0 0 30 0\n"])
        def read(path):
            if path == "/proc/stat":
                return StringIO(next(stats))
            return StringIO("MemTotal: 8192 kB\nMemFree: 1024 kB\nMemAvailable: 3072 kB\n")
        with patch("builtins.open", side_effect=read), patch.object(self.panel.time, "monotonic", side_effect=[10, 15, 15.1]):
            first = self.panel.server_metrics()
            self.assertIsNone(first["cpu_percent"])
            second = self.panel.server_metrics()
            self.assertEqual(second["cpu_percent"], 50)
            self.assertEqual(second["memory_total"], 8192 * 1024)
            self.assertEqual(second["memory_used"], 5120 * 1024)
            self.assertEqual(self.panel.server_metrics(), second)

    def test_missing_proc_reports_unavailable(self):
        with patch("builtins.open", side_effect=OSError):
            self.assertEqual(self.panel.server_metrics(), {
                "cpu_percent": None, "memory_used": None, "memory_total": None,
            })
