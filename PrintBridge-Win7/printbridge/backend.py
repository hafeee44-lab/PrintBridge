"""
The part that actually puts ink on paper.

On Windows this shells out to SumatraPDF, which prints a PDF with no dialog
and - crucially - with rescaling switched off, so a page laid out at an exact
physical size comes out at that size. The printer's own Windows driver does
the rendering, which is the whole reason this bridge exists: the M1132 is
host-based and cannot rasterise anything itself.
"""

from __future__ import annotations

import json
import os
import platform
import re
import shutil
import subprocess
import sys
import time

IS_WINDOWS = platform.system() == "Windows"

_PS_LIST = (
    "$ErrorActionPreference='SilentlyContinue';"
    "$p = Get-CimInstance Win32_Printer;"
    "if (-not $p) { $p = Get-WmiObject Win32_Printer };"
    "$p | Select-Object Name,Default,WorkOffline,PrinterStatus,DriverName,PortName"
    " | ConvertTo-Json -Compress -Depth 3"
)


# Windows 7 ships PowerShell 2.0, which has no ConvertTo-Json. Same query,
# plain text out.
_PS2_LIST = (
    "$ErrorActionPreference='SilentlyContinue';"
    "Get-WmiObject Win32_Printer | ForEach-Object {"
    "$_.Name + '|' + $_.Default + '|' + $_.WorkOffline + '|' + "
    "$_.DriverName + '|' + $_.PortName }"
)


def _powershell(script, timeout=25):
    exe = shutil.which("powershell") or shutil.which("pwsh")
    if not exe:
        return None
    try:
        r = subprocess.run(
            [exe, "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True, timeout=timeout,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    if r.returncode != 0:
        return None
    return r.stdout.decode("utf-8", "replace").strip()


class Printer:
    def __init__(self, name, default=False, offline=False, driver="", port=""):
        self.name = name
        self.default = default
        self.offline = offline
        self.driver = driver
        self.port = port

    def as_dict(self):
        return {
            "name": self.name, "default": self.default,
            "offline": self.offline, "driver": self.driver, "port": self.port,
        }


def _enum_printers_win32():
    """Ask the print spooler itself. No PowerShell, no WMI, no admin.

    WMI can be slow, disabled, or filtered by security software, and
    PowerShell 2.0 on Windows 7 has no ConvertTo-Json. EnumPrinters is the
    same call the Devices and Printers window makes, so if Windows can see
    the printer, this sees it too.
    """
    if not IS_WINDOWS:
        return []
    try:
        import ctypes
        from ctypes import wintypes
    except ImportError:
        return []

    class PRINTER_INFO_2W(ctypes.Structure):
        _fields_ = [
            ("pServerName", wintypes.LPWSTR),
            ("pPrinterName", wintypes.LPWSTR),
            ("pShareName", wintypes.LPWSTR),
            ("pPortName", wintypes.LPWSTR),
            ("pDriverName", wintypes.LPWSTR),
            ("pComment", wintypes.LPWSTR),
            ("pLocation", wintypes.LPWSTR),
            ("pDevMode", ctypes.c_void_p),
            ("pSepFile", wintypes.LPWSTR),
            ("pPrintProcessor", wintypes.LPWSTR),
            ("pDatatype", wintypes.LPWSTR),
            ("pParameters", wintypes.LPWSTR),
            ("pSecurityDescriptor", ctypes.c_void_p),
            ("Attributes", wintypes.DWORD),
            ("Priority", wintypes.DWORD),
            ("DefaultPriority", wintypes.DWORD),
            ("StartTime", wintypes.DWORD),
            ("UntilTime", wintypes.DWORD),
            ("Status", wintypes.DWORD),
            ("cJobs", wintypes.DWORD),
            ("AveragePPM", wintypes.DWORD),
        ]

    try:
        spool = ctypes.WinDLL("winspool.drv")
    except OSError:
        return []

    ENUM_LOCAL_AND_CONNECTIONS = 0x02 | 0x04
    ATTRIBUTE_WORK_OFFLINE = 0x400

    needed = wintypes.DWORD(0)
    returned = wintypes.DWORD(0)
    try:
        spool.EnumPrintersW(ENUM_LOCAL_AND_CONNECTIONS, None, 2, None, 0,
                            ctypes.byref(needed), ctypes.byref(returned))
        if not needed.value:
            return []

        buf = ctypes.create_string_buffer(needed.value)
        if not spool.EnumPrintersW(ENUM_LOCAL_AND_CONNECTIONS, None, 2, buf,
                                   needed.value, ctypes.byref(needed),
                                   ctypes.byref(returned)):
            return []

        default_name = ""
        size = wintypes.DWORD(0)
        spool.GetDefaultPrinterW(None, ctypes.byref(size))
        if size.value:
            name_buf = ctypes.create_unicode_buffer(size.value)
            if spool.GetDefaultPrinterW(name_buf, ctypes.byref(size)):
                default_name = name_buf.value or ""

        rows = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_2W))
        found = []
        for i in range(returned.value):
            row = rows[i]
            name = row.pPrinterName or ""
            if not name:
                continue
            found.append(Printer(
                name,
                default=bool(default_name
                             and name.lower() == default_name.lower()),
                offline=bool(row.Attributes & ATTRIBUTE_WORK_OFFLINE),
                driver=row.pDriverName or "",
                port=row.pPortName or "",
            ))
        return found
    except (OSError, ValueError, AttributeError):
        return []


def list_printers(simulate=False):
    """Installed printers, best effort. Never raises."""
    if simulate or not IS_WINDOWS:
        return [
            Printer("Simulated M1132", default=True, driver="foo2zjs (simulated)"),
            Printer("Simulated Second Printer"),
        ]

    printers = _enum_printers_win32()
    if printers:
        return printers

    out = _powershell(_PS_LIST)
    printers = []
    if out:
        try:
            data = json.loads(out)
        except ValueError:
            data = None
        if isinstance(data, dict):
            data = [data]
        for row in data or []:
            nm = (row.get("Name") or "").strip()
            if not nm:
                continue
            printers.append(Printer(
                nm,
                default=bool(row.get("Default")),
                offline=bool(row.get("WorkOffline")),
                driver=(row.get("DriverName") or "").strip(),
                port=(row.get("PortName") or "").strip(),
            ))

    if not printers:                      # PowerShell 2.0
        out = _powershell(_PS2_LIST)
        for line in (out or "").splitlines():
            bits = line.split("|")
            if len(bits) < 5 or not bits[0].strip():
                continue
            printers.append(Printer(
                bits[0].strip(),
                default=bits[1].strip().lower() == "true",
                offline=bits[2].strip().lower() == "true",
                driver=bits[3].strip(),
                port=bits[4].strip(),
            ))

    if not printers:                      # last resort: registry via reg.exe
        try:
            r = subprocess.run(
                ["reg", "query",
                 r"HKCU\Software\Microsoft\Windows NT\CurrentVersion\Devices"],
                capture_output=True, timeout=15,
            )
            for line in r.stdout.decode("utf-8", "replace").splitlines():
                m = re.match(r"\s{4}(.+?)\s{4}REG_SZ", line)
                if m:
                    printers.append(Printer(m.group(1).strip()))
        except (subprocess.SubprocessError, OSError):
            pass

    return printers


VIRTUAL_RE = re.compile(
    r"xps document writer|print to pdf|microsoft print|onenote|"
    r"\bfax\b|adobe pdf|cutepdf|pdfcreator|foxit .*pdf|bullzip|"
    r"pdf(24| ?printer| ?writer)|snagit|nitro pdf|dopdf|"
    r"send to (onenote|bluetooth)|remote desktop",
    re.I)


def is_virtual(printer):
    """True for the fake printers Windows installs: XPS, Print to PDF, Fax."""
    return bool(VIRTUAL_RE.search(printer.name)
                or VIRTUAL_RE.search(printer.driver or "")
                or (printer.port or "").upper().startswith(
                    ("PORTPROMPT", "SHRFAX", "XPSPORT", "NUL")))


def default_printer(printers):
    """The printer to share when nobody said which one.

    Windows ships with XPS Document Writer and Print to PDF installed, and
    on a PC where nobody ever changed it one of those is the system default.
    Sharing it means every phone job lands in a Save As dialog nobody sees,
    so real hardware wins over the default flag.
    """
    real = [p for p in printers if not is_virtual(p)]
    pool = real or printers

    for p in pool:
        if p.default and not p.offline:
            return p
    for p in pool:
        if not p.offline:
            return p
    return pool[0] if pool else None


# ---------------------------------------------------------------------------
# SumatraPDF
# ---------------------------------------------------------------------------

def find_sumatra(script_dir):
    """Any SumatraPDF*.exe we can reach.

    The portable download is named after its version, so match on the prefix
    rather than an exact file name - dropping the downloaded .exe into this
    folder should just work, with no renaming.
    """
    roots = [script_dir,
             os.path.join(script_dir, "bin"),
             os.path.join(script_dir, "setup")]
    for env in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"):
        base = os.environ.get(env)
        if base:
            roots.append(os.path.join(base, "SumatraPDF"))

    for root in roots:
        try:
            entries = sorted(os.listdir(root))
        except OSError:
            continue
        for n in entries:
            low = n.lower()
            if (low.startswith("sumatrapdf") and low.endswith(".exe")
                    and "install" not in low and "uninstall" not in low):
                cand = os.path.join(root, n)
                if os.path.isfile(cand):
                    return os.path.abspath(cand)

    return shutil.which("SumatraPDF.exe") or shutil.which("SumatraPDF")


PAGE_COUNT_RE = re.compile(rb"/Count\s+(\d+)")
PAGE_OBJ_RE = re.compile(rb"/Type\s*/Page[^sA-Za-z]")


def count_pdf_pages(path):
    """Best-effort page count. None when we cannot tell.

    Only used to work out the running order for the second pass of a
    two-sided job, so a wrong answer costs an option, not a print.
    """
    try:
        with open(path, "rb") as fh:
            data = fh.read(8 * 1024 * 1024)
    except OSError:
        return None
    counts = [int(m.group(1)) for m in PAGE_COUNT_RE.finditer(data)]
    objs = len(PAGE_OBJ_RE.findall(data))
    if objs:
        return objs
    if counts:
        return max(counts)
    return None


def expand_pages(spec, total):
    """'1-3,7' -> [1,2,3,7];  'odd'/'even' -> the matching page numbers."""
    if not total:
        return []
    spec = (spec or "").strip().lower()
    if spec in ("odd", ""):
        base = list(range(1, total + 1, 2)) if spec == "odd" else \
            list(range(1, total + 1))
    elif spec == "even":
        base = list(range(2, total + 1, 2))
    else:
        base = []
        for part in spec.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                a, _, b = part.partition("-")
                try:
                    lo, hi = int(a), int(b)
                except ValueError:
                    continue
                base.extend(range(max(1, lo), min(total, hi) + 1))
            else:
                try:
                    n = int(part)
                except ValueError:
                    continue
                if 1 <= n <= total:
                    base.append(n)
    return base


class PrintResult:
    def __init__(self, ok, detail="", method=""):
        self.ok, self.detail, self.method = ok, detail, method


class Backend:
    """Turns a file on disk plus a few options into a printed sheet."""

    def __init__(self, script_dir, simulate=False, job_dir=None, log=print):
        self.script_dir = script_dir
        self.simulate = simulate
        self.job_dir = job_dir or os.path.join(script_dir, "simulated-jobs")
        self.log = log
        self.sumatra = None if simulate else find_sumatra(script_dir)

    @property
    def method(self):
        if self.simulate:
            return "simulate"
        if self.sumatra:
            return "sumatrapdf"
        return "shell-printto"

    def rescan(self):
        if not self.simulate:
            self.sumatra = find_sumatra(self.script_dir)

    # -- options ------------------------------------------------------------
    @staticmethod
    def _settings(copies=1, pages="", scale="noscale", mono=False,
                  duplex=False, paper="", subset=""):
        parts = []
        if subset in ("odd", "even"):
            parts.append(subset)
        if pages:
            parts.append(pages)
        scale = (scale or "noscale").lower()
        if scale in ("none", "noscale", "actual"):
            parts.append("noscale")
        elif scale in ("shrink", "auto-fit", "auto"):
            parts.append("shrink")
        else:
            parts.append("fit")
        if copies and copies > 1:
            parts.append("%dx" % int(copies))
        if mono:
            parts.append("monochrome")
        parts.append("duplex" if duplex else "simplex")
        if paper:
            parts.append("paper=%s" % paper)
        return ",".join(parts)

    # -- the main entry point ------------------------------------------------
    def print_file(self, path, printer, copies=1, pages="", scale="noscale",
                   mono=False, duplex=False, paper="", label="", subset="",
                   reverse=False):
        if reverse and not self.simulate:
            # The second pass of a two-sided job on a printer that stacks the
            # other way up. Page order inside one job is the driver's business,
            # so send the pages as separate jobs - then the order is ours.
            total = count_pdf_pages(path)
            wanted = expand_pages(subset or pages, total) if total else []
            if len(wanted) > 1:
                last = PrintResult(True, "", self.method)
                for n in reversed(wanted):
                    last = self.print_file(
                        path, printer, copies=copies, pages=str(n),
                        scale=scale, mono=mono, duplex=duplex, paper=paper,
                        label="%s p%d" % (label, n))
                    if not last.ok:
                        return last
                return PrintResult(True, "%d pages, reverse order"
                                   % len(wanted), self.method)

        if self.simulate:
            os.makedirs(self.job_dir, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            safe = re.sub(r"[^A-Za-z0-9._-]+", "_", label or os.path.basename(path))[:60]
            dest = os.path.join(self.job_dir, "%s-%s" % (stamp, safe or "job"))
            if not os.path.splitext(dest)[1]:
                dest += os.path.splitext(path)[1] or ".bin"
            shutil.copyfile(path, dest)
            self.log("  simulated -> %s" % dest)
            return PrintResult(True, "saved to %s" % dest, "simulate")

        settings = self._settings(copies, pages, scale, mono, duplex, paper,
                                  subset)

        if self.sumatra:
            cmd = [self.sumatra, "-print-to", printer,
                   "-print-settings", settings,
                   "-silent", "-exit-when-done", path]
            try:
                r = subprocess.run(cmd, capture_output=True, timeout=300)
            except subprocess.TimeoutExpired:
                return PrintResult(False, "SumatraPDF timed out", "sumatrapdf")
            except OSError as e:
                return PrintResult(False, "could not run SumatraPDF: %s" % e,
                                   "sumatrapdf")
            if r.returncode == 0:
                return PrintResult(True, settings, "sumatrapdf")
            err = (r.stderr or r.stdout or b"").decode("utf-8", "replace").strip()
            return PrintResult(False, err or "SumatraPDF exit %d" % r.returncode,
                               "sumatrapdf")

        # fallback: whatever app owns the PrintTo verb. Sizing is its choice.
        script = ("Start-Process -FilePath '%s' -Verb PrintTo "
                  "-ArgumentList '\"%s\"' -PassThru | Out-Null"
                  % (path.replace("'", "''"), printer.replace("'", "''")))
        out = _powershell(script, timeout=120)
        if out is None:
            return PrintResult(
                False,
                "SumatraPDF is not installed and Windows has no app registered "
                "to print a PDF. Put SumatraPDF.exe next to Start Print "
                "Bridge.bat and restart.",
                "shell-printto")
        return PrintResult(True, "handed to the default PDF app "
                                 "(exact sizing not guaranteed)", "shell-printto")


def _netsh_profile():
    """Windows 7 has no Get-NetConnectionProfile, but the firewall knows which
    profile is live."""
    try:
        r = subprocess.run(["netsh", "advfirewall", "show", "currentprofile"],
                           capture_output=True, timeout=15)
    except (subprocess.SubprocessError, OSError):
        return []
    for line in r.stdout.decode("utf-8", "replace").splitlines():
        line = line.strip().lower()
        if not line:
            continue
        for word, cat in (("public", "Public"), ("private", "Private"),
                          ("domain", "DomainAuthenticated")):
            if line.startswith(word):
                return [("this network", cat)]
        break
    return []


def network_profiles():
    """[(interface, 'Private'|'Public'|'DomainAuthenticated')] on Windows."""
    if not IS_WINDOWS:
        return []
    out = _powershell(
        "Get-NetConnectionProfile | Select-Object InterfaceAlias,NetworkCategory"
        " | ConvertTo-Json -Compress", timeout=15)
    if not out:
        return _netsh_profile()
    try:
        data = json.loads(out)
    except ValueError:
        return _netsh_profile()
    if isinstance(data, dict):
        data = [data]
    result = []
    for row in data or []:
        cat = row.get("NetworkCategory")
        if isinstance(cat, int):
            cat = {0: "Public", 1: "Private", 2: "DomainAuthenticated"}.get(cat, str(cat))
        result.append((row.get("InterfaceAlias") or "?", cat or "?"))
    return result or _netsh_profile()
