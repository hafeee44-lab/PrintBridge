"""Starts the bridge with no console window, for the auto-start task.

Kept at the top of the folder so it can find the package no matter what
working directory the task scheduler hands it.
"""
import os
import sys

here = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, here)

from printbridge.__main__ import main   # noqa: E402

args = sys.argv[1:]
if not any(a == "--log-file" for a in args):
    args += ["--log-file", os.path.join(here, "printbridge.log")]
sys.exit(main(args))
