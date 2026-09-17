"""
The other half of a multifunction printer.

An MFP has a scanner under the lid, and it is USB-only for exactly the same
reason the printer was. Windows can already drive it - that is what WIA is for
- so the bridge does for scanning what it does for printing: talk to the
hardware locally, and answer a standard protocol on the network so phones find
it with nothing installed.

WIA is reached through PowerShell rather than a COM binding, because that
works the whole way back to PowerShell 2.0 on Windows 7 and needs no package
installed. Everything here returns rather than raises; a machine with no
scanner simply reports none.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import tempfile
import time

IS_WINDOWS = platform.system() == "Windows"

WIA_FORMAT_JPEG = "{B96B3CAE-0728-11D3-9D7B-0000F81EF32E}"

# WIA property ids we care about
P_XRES, P_YRES = 6147, 6148
P_XPOS, P_YPOS = 6149, 6150
P_XEXTENT, P_YEXTENT = 6151, 6152
P_DATATYPE, P_DEPTH = 4103, 4104

DATATYPE = {"bw": 0, "gray": 2, "color": 3}
DEPTH = {"bw": 1, "gray": 8, "color": 24}
MODES = ("color", "gray", "bw")

DEFAULT_RESOLUTIONS = (75, 150, 200, 300, 600)


def _powershell(script, timeout=120):
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return None
    try:
        proc = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-STA", "-Command", script],
            capture_output=True, timeout=timeout)
    except (subprocess.SubprocessError, OSError):
        return None
    out = proc.stdout.decode("utf-8", "replace").strip()
    err = proc.stderr.decode("utf-8", "replace").strip()
    if proc.returncode != 0 and not out:
        return "ERR|" + (err.splitlines()[0] if err else "powershell failed")
    return out


class Scanner:
    def __init__(self, device_id, name, resolutions=None,
                 max_width_in=8.5, max_height_in=11.7, has_feeder=False):
        self.device_id = device_id
        self.name = name or "Scanner"
        self.resolutions = list(resolutions or DEFAULT_RESOLUTIONS)
        self.max_width_in = max_width_in
        self.max_height_in = max_height_in
        self.has_feeder = has_feeder

    def as_dict(self):
        return {
            "id": self.device_id, "name": self.name,
            "resolutions": self.resolutions,
            "maxWidthIn": round(self.max_width_in, 3),
            "maxHeightIn": round(self.max_height_in, 3),
            "hasFeeder": self.has_feeder,
            "modes": list(MODES),
        }

    def __repr__(self):
        return "Scanner(%r, %r)" % (self.name, self.device_id)


_LIST_PS = r"""
$ErrorActionPreference = 'SilentlyContinue'
$dm = New-Object -ComObject WIA.DeviceManager
if ($dm -eq $null) { Write-Output 'ERR|no WIA on this PC'; exit }
foreach ($info in $dm.DeviceInfos) {
  if ($info.Type -ne 1) { continue }
  $name = ''
  foreach ($p in $info.Properties) { if ($p.Name -eq 'Name') { $name = [string]$p.Value } }
  $feeder = 0
  try {
    $dev = $info.Connect()
    foreach ($p in $dev.Properties) {
      if ($p.PropertyID -eq 3088) { if (([int]$p.Value -band 1) -ne 0) { $feeder = 1 } }
    }
  } catch { }
  Write-Output ('DEV|' + $info.DeviceID + '|' + $name + '|' + $feeder)
}
"""


def list_scanners():
    """Scanners Windows can see. Empty list when there are none, or no WIA."""
    if not IS_WINDOWS:
        return []
    out = _powershell(_LIST_PS, timeout=60)
    if not out or out.startswith("ERR|"):
        return []
    found = []
    for line in out.splitlines():
        parts = line.strip().split("|")
        if len(parts) < 3 or parts[0] != "DEV":
            continue
        device_id, name = parts[1], parts[2]
        feeder = len(parts) > 3 and parts[3].strip() == "1"
        if device_id:
            found.append(Scanner(device_id, name, has_feeder=feeder))
    return found


def default_scanner(scanners=None):
    scanners = list_scanners() if scanners is None else scanners
    return scanners[0] if scanners else None


_SCAN_PS = r"""
$ErrorActionPreference = 'Stop'
try {
  $dm = New-Object -ComObject WIA.DeviceManager
  $info = $null
  foreach ($d in $dm.DeviceInfos) { if ($d.DeviceID -eq '__DEVICE__') { $info = $d } }
  if ($info -eq $null) { foreach ($d in $dm.DeviceInfos) { if ($d.Type -eq 1 -and $info -eq $null) { $info = $d } } }
  if ($info -eq $null) { Write-Output 'ERR|no scanner found'; exit }

  $dev  = $info.Connect()
  $item = $dev.Items.Item(1)

  function SetProp($target, $id, $value) {
    foreach ($p in $target.Properties) {
      if ($p.PropertyID -eq $id) { try { $p.Value = $value } catch { } }
    }
  }
  function MaxOf($target, $id) {
    foreach ($p in $target.Properties) {
      if ($p.PropertyID -eq $id) { try { return [int]$p.SubTypeMax } catch { return 0 } }
    }
    return 0
  }

  # resolution first - the device recalculates its extents from it
  SetProp $item __P_XRES__ __DPI__
  SetProp $item __P_YRES__ __DPI__
  SetProp $item __P_DATATYPE__ __DATATYPE__
  SetProp $item __P_DEPTH__ __DEPTH__

  $xmax = MaxOf $item __P_XEXTENT__
  $ymax = MaxOf $item __P_YEXTENT__
  if ($xmax -gt 0) { SetProp $item __P_XPOS__ 0; SetProp $item __P_XEXTENT__ $xmax }
  if ($ymax -gt 0) { SetProp $item __P_YPOS__ 0; SetProp $item __P_YEXTENT__ $ymax }

  $img = $item.Transfer('__FORMAT__')

  # not every scanner will hand back a JPEG, so convert whatever arrived
  if ($img.FormatID -ne '__FORMAT__') {
    $proc = New-Object -ComObject WIA.ImageProcess
    $proc.Filters.Add($proc.FilterInfos.Item('Convert').FilterID)
    $proc.Filters.Item(1).Properties.Item('FormatID').Value = '__FORMAT__'
    try { $proc.Filters.Item(1).Properties.Item('Quality').Value = 88 } catch { }
    $img = $proc.Apply($img)
  }

  if (Test-Path '__OUT__') { Remove-Item '__OUT__' -Force }
  $img.SaveFile('__OUT__')
  Write-Output ('OK|' + $img.Width + '|' + $img.Height + '|' + $img.HorizontalResolution)
} catch {
  Write-Output ('ERR|' + $_.Exception.Message)
}
"""


class ScanResult:
    def __init__(self, ok, path=None, width=0, height=0, dpi=0, detail=""):
        self.ok, self.path = ok, path
        self.width, self.height, self.dpi = width, height, dpi
        self.detail = detail

    def as_dict(self):
        return {"ok": self.ok, "width": self.width, "height": self.height,
                "dpi": self.dpi, "detail": self.detail}


def scan_page(device_id="", dpi=300, mode="color", out_dir=None, timeout=180):
    """Pull one page off the glass. Always returns a ScanResult."""
    if not IS_WINDOWS:
        return ScanResult(False, detail="scanning needs Windows")

    mode = mode if mode in DATATYPE else "color"
    try:
        dpi = max(50, min(1200, int(dpi)))
    except (TypeError, ValueError):
        dpi = 300

    out_dir = out_dir or tempfile.gettempdir()
    try:
        os.makedirs(out_dir, exist_ok=True)
    except OSError:
        pass
    out = os.path.join(out_dir, "pbscan-%s.jpg" % time.strftime("%Y%m%d-%H%M%S"))

    script = _SCAN_PS
    for token, value in (
            ("__DEVICE__", (device_id or "").replace("'", "''")),
            ("__OUT__", out.replace("'", "''")),
            ("__FORMAT__", WIA_FORMAT_JPEG),
            ("__DPI__", str(dpi)),
            ("__DATATYPE__", str(DATATYPE[mode])),
            ("__DEPTH__", str(DEPTH[mode])),
            ("__P_XRES__", str(P_XRES)), ("__P_YRES__", str(P_YRES)),
            ("__P_XPOS__", str(P_XPOS)), ("__P_YPOS__", str(P_YPOS)),
            ("__P_XEXTENT__", str(P_XEXTENT)), ("__P_YEXTENT__", str(P_YEXTENT)),
            ("__P_DATATYPE__", str(P_DATATYPE)), ("__P_DEPTH__", str(P_DEPTH))):
        script = script.replace(token, value)

    answer = _powershell(script, timeout=timeout)
    if not answer:
        return ScanResult(False, detail="the scanner did not answer")

    line = [ln for ln in answer.splitlines() if ln.startswith(("OK|", "ERR|"))]
    if not line:
        return ScanResult(False, detail=answer.splitlines()[0][:200] if answer
                          else "no answer from WIA")
    head = line[-1]
    if head.startswith("ERR|"):
        return ScanResult(False, detail=_friendly(head[4:].strip()))

    bits = head.split("|")
    try:
        width, height = int(bits[1]), int(bits[2])
        got_dpi = int(float(bits[3])) or dpi
    except (IndexError, ValueError):
        width = height = 0
        got_dpi = dpi
    if not os.path.exists(out):
        return ScanResult(False, detail="the scan produced no file")
    return ScanResult(True, out, width, height, got_dpi, "scanned at %ddpi" % got_dpi)


def _friendly(message):
    """WIA's HRESULTs are not for humans."""
    text = (message or "").strip()
    known = [
        ("0x80210006", "the scanner is busy"),
        ("0x80210015", "no scanner is connected"),
        ("0x80210021", "there is no paper in the feeder"),
        ("0x80210064", "the scan was cancelled"),
        ("0x8021000C", "the lid or cover is open"),
        ("0x80210005", "the scanner is offline"),
    ]
    low = text.lower()
    for code, plain in known:
        if code.lower() in low:
            return plain
    return text[:200] or "the scanner reported a problem"
