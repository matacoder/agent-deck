import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from support import PanelCase, ROOT

VM_STAT = """Mach Virtual Memory Statistics: (page size of 16384 bytes)
Pages free:                               10000.
Pages active:                            200000.
Pages inactive:                           90000.
Pages speculative:                         5000.
"Translation faults":                 123456789.
"""


def fake_run(outputs, calls):
    def run(arguments, **options):
        calls.append((arguments, options))
        output = outputs[arguments[0]]
        if isinstance(output, Exception):
            raise output
        return SimpleNamespace(returncode=0, stdout=output)
    return run


class MacCommandMetricsTests(PanelCase):
    def setUp(self):
        super().setUp()
        self.panel.macos_metrics._cache = None  # The module outlives a test; its figures must not.

    def metrics(self, outputs, cpus=4):
        calls = []
        with patch.object(self.panel.sys, 'platform', 'darwin'), patch.dict('sys.modules', psutil=None), \
                patch.object(self.panel.os, 'cpu_count', return_value=cpus), \
                patch.object(self.panel.subprocess, 'run', side_effect=fake_run(outputs, calls)):
            return self.panel.server_metrics(), calls

    def test_figures_come_from_ps_sysctl_and_vm_stat_without_psutil(self):
        total = 8 * 1024 ** 3
        result, calls = self.metrics({'ps': ' 50.0\n 30,0\n 20.0\n', 'sysctl': f'{total}\n', 'vm_stat': VM_STAT})
        self.assertEqual(result, {'cpu_percent': 25.0, 'memory_total': total,
                                  'memory_used': total - (10000 + 90000) * 16384})
        for arguments, options in calls:
            self.assertIsInstance(arguments, list)
            self.assertEqual(options['input'], '')
            self.assertIn('timeout', options)
            self.assertNotIn('shell', options)
        self.assertEqual([call[0][0] for call in calls], ['ps', 'sysctl', 'vm_stat'])

    def test_commands_run_at_most_once_a_second(self):
        outputs = {'ps': '10\n', 'sysctl': '1000\n', 'vm_stat': VM_STAT}
        calls = []
        with patch.object(self.panel.sys, 'platform', 'darwin'), patch.dict('sys.modules', psutil=None), \
                patch.object(self.panel.time, 'monotonic', side_effect=[100, 100.5, 102]), \
                patch.object(self.panel.subprocess, 'run', side_effect=fake_run(outputs, calls)):
            for _ in range(3):
                self.panel.server_metrics()
        self.assertEqual(len(calls), 6)

    def test_failed_commands_leave_figures_empty(self):
        failure = subprocess.TimeoutExpired('ps', 3)
        result, _ = self.metrics({'ps': failure, 'sysctl': FileNotFoundError(), 'vm_stat': 'garbage'})
        self.assertEqual(result, {'cpu_percent': None, 'memory_used': None, 'memory_total': None})

    def test_cpu_share_is_capped_at_one_hundred(self):
        result, _ = self.metrics({'ps': '400\n100\n', 'sysctl': 'x', 'vm_stat': ''}, cpus=4)
        self.assertEqual(result['cpu_percent'], 100)
        self.assertIsNone(result['memory_total'])


class MacInstallerPackagesTests(unittest.TestCase):
    def test_installer_installs_no_python_packages(self):
        script = (ROOT / 'install-macos.sh').read_text()
        self.assertNotIn('pip install', script)
        self.assertIn('-m venv --without-pip', script)


if __name__ == '__main__':
    unittest.main()
