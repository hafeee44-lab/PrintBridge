"""Entry point for the single-file build.

Kept separate from run_hidden.pyw so PyInstaller has a plain .py to start
from, and so the frozen build can default to the tray without changing how
the folder version behaves.
"""
import os
import sys

if not getattr(sys, "frozen", False):
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from printbridge.__main__ import main   # noqa: E402

args = sys.argv[1:]
beside_exe = os.path.dirname(os.path.abspath(sys.executable))

if not any(a == "--log-file" for a in args):
    args += ["--log-file", os.path.join(beside_exe, "printbridge.log")]
if "--tray" not in args and "--no-tray" not in args:
    args += ["--tray"]
args = [a for a in args if a != "--no-tray"]

sys.exit(main(args))
