"""Compatibility entry for the shared, now packaged guest-probe regressions."""
import sys
from pathlib import Path
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tests.test_guest_security_probe import GuestProbeTests, DownloadEntryTests
if __name__ == '__main__':
    unittest.main()
