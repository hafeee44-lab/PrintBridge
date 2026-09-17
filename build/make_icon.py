"""Write printbridge.ico next to this script, for the exe and the tray."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from printbridge import icons   # noqa: E402

out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "printbridge.ico")
with open(out, "wb") as fh:
    fh.write(icons.ico((16, 32, 48, 64, 128, 256)))
print("wrote %s (%d bytes)" % (out, os.path.getsize(out)))
