"""
Printing straight to a Windows printer, with no other application involved.

The bridge used to shell out to SumatraPDF because a PDF has to be turned into
something a printer driver understands, and Windows has no built-in way to do
that from a script. PDFium does the turning now, and what is left is the part
Windows has always offered: open a device context on the printer, hand it a
bitmap, say where it goes.

Doing it here rather than through another program buys three things that were
awkward before - the exact physical size of every page, the duplex edge the
client actually asked for, and one less thing to install.

Everything in here is ctypes against gdi32 and winspool. There is no build
step and no compiled dependency; on anything that is not Windows the module
imports cleanly and reports itself unavailable.
"""

from __future__ import annotations

import platform

IS_WINDOWS = platform.system() == "Windows"

from . import render

if IS_WINDOWS:
    import ctypes
    from ctypes import wintypes

    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    winspool = ctypes.WinDLL("winspool.drv", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
else:
    ctypes = wintypes = gdi32 = winspool = kernel32 = None

# -- GetDeviceCaps ----------------------------------------------------------
HORZRES, VERTRES = 8, 10
LOGPIXELSX, LOGPIXELSY = 88, 90
PHYSICALWIDTH, PHYSICALHEIGHT = 110, 111
PHYSICALOFFSETX, PHYSICALOFFSETY = 112, 113

# -- DEVMODE ----------------------------------------------------------------
CCHDEVICENAME = CCHFORMNAME = 32
DM_ORIENTATION = 0x00000001
DM_PAPERSIZE   = 0x00000002
DM_COPIES      = 0x00000100
DM_COLOR       = 0x00000800
DM_DUPLEX      = 0x00001000
DM_COLLATE     = 0x00008000
DM_OUT_BUFFER  = 2
DM_IN_BUFFER   = 8

DMDUP_SIMPLEX, DMDUP_VERTICAL, DMDUP_HORIZONTAL = 1, 2, 3
DMCOLOR_MONOCHROME, DMCOLOR_COLOR = 1, 2
DMCOLLATE_FALSE, DMCOLLATE_TRUE = 0, 1
DMPAPER = {"letter": 1, "legal": 5, "a4": 9, "a5": 11, "a3": 8, "executive": 7}

# -- blitting ---------------------------------------------------------------
BI_RGB, DIB_RGB_COLORS, SRCCOPY = 0, 0, 0x00CC0020
GDI_ERROR = 0xFFFFFFFF

# HALFTONE is for screens. On a printer DC it makes some drivers hand back a
# blank sheet, and it buys nothing here anyway - the page is rasterised at
# exactly the size it will occupy, so there is no stretching left to do.
BLACKONWHITE, COLORONCOLOR, HALFTONE = 1, 3, 4
STRETCH_MODE = COLORONCOLOR


if IS_WINDOWS:
    class DEVMODEW(ctypes.Structure):
        _fields_ = [
            ("dmDeviceName", wintypes.WCHAR * CCHDEVICENAME),
            ("dmSpecVersion", wintypes.WORD),
            ("dmDriverVersion", wintypes.WORD),
            ("dmSize", wintypes.WORD),
            ("dmDriverExtra", wintypes.WORD),
            ("dmFields", wintypes.DWORD),
            ("dmOrientation", ctypes.c_short),
            ("dmPaperSize", ctypes.c_short),
            ("dmPaperLength", ctypes.c_short),
            ("dmPaperWidth", ctypes.c_short),
            ("dmScale", ctypes.c_short),
            ("dmCopies", ctypes.c_short),
            ("dmDefaultSource", ctypes.c_short),
            ("dmPrintQuality", ctypes.c_short),
            ("dmColor", ctypes.c_short),
            ("dmDuplex", ctypes.c_short),
            ("dmYResolution", ctypes.c_short),
            ("dmTTOption", ctypes.c_short),
            ("dmCollate", ctypes.c_short),
            ("dmFormName", wintypes.WCHAR * CCHFORMNAME),
            ("dmLogPixels", wintypes.WORD),
            ("dmBitsPerPel", wintypes.DWORD),
            ("dmPelsWidth", wintypes.DWORD),
            ("dmPelsHeight", wintypes.DWORD),
            ("dmNup", wintypes.DWORD),
            ("dmDisplayFrequency", wintypes.DWORD),
            ("dmICMMethod", wintypes.DWORD),
            ("dmICMIntent", wintypes.DWORD),
            ("dmMediaType", wintypes.DWORD),
            ("dmDitherType", wintypes.DWORD),
            ("dmReserved1", wintypes.DWORD),
            ("dmReserved2", wintypes.DWORD),
            ("dmPanningWidth", wintypes.DWORD),
            ("dmPanningHeight", wintypes.DWORD),
        ]

    class DOCINFOW(ctypes.Structure):
        _fields_ = [
            ("cbSize", ctypes.c_int),
            ("lpszDocName", wintypes.LPCWSTR),
            ("lpszOutput", wintypes.LPCWSTR),
            ("lpszDatatype", wintypes.LPCWSTR),
            ("fwType", wintypes.DWORD),
        ]

    class BITMAPINFOHEADER(ctypes.Structure):
        _fields_ = [
            ("biSize", wintypes.DWORD),
            ("biWidth", ctypes.c_long),
            ("biHeight", ctypes.c_long),
            ("biPlanes", wintypes.WORD),
            ("biBitCount", wintypes.WORD),
            ("biCompression", wintypes.DWORD),
            ("biSizeImage", wintypes.DWORD),
            ("biXPelsPerMeter", ctypes.c_long),
            ("biYPelsPerMeter", ctypes.c_long),
            ("biClrUsed", wintypes.DWORD),
            ("biClrImportant", wintypes.DWORD),
        ]

    gdi32.CreateDCW.restype = wintypes.HDC
    gdi32.CreateDCW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR,
                                wintypes.LPCWSTR, ctypes.c_void_p]
    gdi32.GetDeviceCaps.restype = ctypes.c_int
    gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
    gdi32.StartDocW.restype = ctypes.c_int
    gdi32.StartDocW.argtypes = [wintypes.HDC, ctypes.POINTER(DOCINFOW)]
    gdi32.StretchDIBits.restype = ctypes.c_int
    gdi32.StretchDIBits.argtypes = [
        wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT, wintypes.DWORD]
    winspool.OpenPrinterW.argtypes = [wintypes.LPWSTR,
                                      ctypes.POINTER(wintypes.HANDLE),
                                      ctypes.c_void_p]
    winspool.DocumentPropertiesW.restype = ctypes.c_long
    winspool.DocumentPropertiesW.argtypes = [
        wintypes.HWND, wintypes.HANDLE, wintypes.LPWSTR,
        ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD]

    # Every one of these takes a handle. Without an argtypes entry ctypes
    # marshals a Python int as a C int, which is 32 bits - and a 64-bit
    # Windows hands out handles above 0x7FFFFFFF whenever it feels like it.
    # The result is a job that prints fine until the day it does not, with
    # "OverflowError: int too long to convert" and nothing to point at. So
    # every call gets a signature, not just the interesting ones.
    for _name, _restype, _args in (
            ("StartPage", ctypes.c_int, [wintypes.HDC]),
            ("EndPage", ctypes.c_int, [wintypes.HDC]),
            ("EndDoc", ctypes.c_int, [wintypes.HDC]),
            ("AbortDoc", ctypes.c_int, [wintypes.HDC]),
            ("DeleteDC", wintypes.BOOL, [wintypes.HDC]),
            ("SetStretchBltMode", ctypes.c_int, [wintypes.HDC, ctypes.c_int]),
            ("SetBrushOrgEx", wintypes.BOOL,
             [wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_void_p]),
    ):
        _fn = getattr(gdi32, _name)
        _fn.restype, _fn.argtypes = _restype, _args

    winspool.ClosePrinter.restype = wintypes.BOOL
    winspool.ClosePrinter.argtypes = [wintypes.HANDLE]
    winspool.OpenPrinterW.restype = wintypes.BOOL


def available():
    """Can this machine print without any other application?"""
    return bool(IS_WINDOWS and render.available())


MAX_RENDER_DPI = 300      # a laser at 600dpi would want 139MB for one A4 page


class PrintError(Exception):
    pass


def _flip_rows(raster):
    """The same image with its rows in the opposite order.

    One buffer copy done in C rather than a Python loop - an A4 page at 300dpi
    is nine million pixels and a per-row Python loop would be felt.
    """
    height, stride = raster.height, raster.stride
    out = (ctypes.c_ubyte * (stride * height))()
    src = ctypes.addressof(raster.buffer)
    dst = ctypes.addressof(out)
    for row in range(height):
        ctypes.memmove(dst + (height - 1 - row) * stride, src + row * stride, stride)
    return out


DC_DUPLEX, DC_COLORDEVICE = 7, 32


def device_can(printer, capability):
    """Ask the driver whether it supports something, rather than assuming."""
    if not IS_WINDOWS or not printer:
        return False
    try:
        fn = winspool.DeviceCapabilitiesW
        fn.restype = ctypes.c_int
        fn.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.WORD,
                       wintypes.LPWSTR, ctypes.c_void_p]
        return fn(printer, None, capability, None, None) == 1
    except (OSError, ValueError, AttributeError):
        return False


def _devmode(printer, copies=1, duplex=False, duplex_edge="long",
             mono=False, paper=""):
    """The driver's own defaults, with the few things we care about changed.

    Asking the driver to merge the change (DM_IN_BUFFER) rather than writing
    the structure ourselves means a printer that cannot do what we asked says
    so now, instead of quietly ignoring it later.
    """
    handle = wintypes.HANDLE()
    if not winspool.OpenPrinterW(printer, ctypes.byref(handle), None):
        raise PrintError("could not open printer %r" % printer)
    try:
        need = winspool.DocumentPropertiesW(None, handle, printer, None, None, 0)
        if need <= 0:
            raise PrintError("the driver would not describe its settings")
        buf = ctypes.create_string_buffer(need)
        if winspool.DocumentPropertiesW(None, handle, printer, buf, None,
                                        DM_OUT_BUFFER) < 0:
            raise PrintError("could not read the driver's default settings")

        dm = ctypes.cast(buf, ctypes.POINTER(DEVMODEW)).contents
        fields = 0

        if copies and copies > 1:
            dm.dmCopies = max(1, min(999, int(copies)))
            dm.dmCollate = DMCOLLATE_TRUE
            fields |= DM_COPIES | DM_COLLATE

        # Touch as little of the DEVMODE as possible. Every field we claim is
        # a field the driver has to honour, and asking a mono laser for colour
        # or a printer with no duplexer for a duplex setting is a good way to
        # get a job it accepts and then cannot make sense of.
        #
        # DMDUP_VERTICAL is the long-edge flip, DMDUP_HORIZONTAL the short one:
        # the names describe the axis the paper turns about, which reads the
        # opposite way round to how binding edges are usually named.
        if duplex and device_can(printer, DC_DUPLEX):
            dm.dmDuplex = (DMDUP_HORIZONTAL if duplex_edge == "short"
                           else DMDUP_VERTICAL)
            fields |= DM_DUPLEX

        if mono:
            dm.dmColor = DMCOLOR_MONOCHROME
            fields |= DM_COLOR
        elif device_can(printer, DC_COLORDEVICE):
            dm.dmColor = DMCOLOR_COLOR
            fields |= DM_COLOR

        kind = DMPAPER.get((paper or "").strip().lower())
        if kind:
            dm.dmPaperSize = kind
            fields |= DM_PAPERSIZE

        dm.dmFields |= fields
        if winspool.DocumentPropertiesW(None, handle, printer, buf, buf,
                                        DM_IN_BUFFER | DM_OUT_BUFFER) < 0:
            raise PrintError("the driver rejected those settings")
        return buf
    finally:
        winspool.ClosePrinter(handle)


class PrinterDC:
    """A device context on a real printer, and what it can tell us about paper."""

    def __init__(self, printer, log=None, debug=False, **settings):
        self.printer = printer
        self.log = log or (lambda m: None)
        self.debug = debug
        self.prefer_bottom_up = False
        self.job_id = 0
        self.devmode = _devmode(printer, **settings)
        self.hdc = gdi32.CreateDCW("WINSPOOL", printer, None, self.devmode)
        if not self.hdc:
            raise PrintError("could not open a device context on %r" % printer)
        self._doc_open = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, *a):
        if self._doc_open:
            if exc_type is None:
                gdi32.EndDoc(self.hdc)
            else:
                gdi32.AbortDoc(self.hdc)
            self._doc_open = False
        if self.hdc:
            gdi32.DeleteDC(self.hdc)
            self.hdc = None
        return False

    def caps(self):
        g = lambda index: gdi32.GetDeviceCaps(self.hdc, index)
        dpi_x, dpi_y = g(LOGPIXELSX) or 300, g(LOGPIXELSY) or 300
        area_w, area_h = g(HORZRES), g(VERTRES)
        off_x, off_y = g(PHYSICALOFFSETX), g(PHYSICALOFFSETY)
        phys_w, phys_h = g(PHYSICALWIDTH), g(PHYSICALHEIGHT)
        if phys_w <= 0 or phys_h <= 0:         # some drivers do not report it
            phys_w, phys_h = area_w + 2*off_x, area_h + 2*off_y
        return {"dpi_x": dpi_x, "dpi_y": dpi_y,
                "area_w": area_w, "area_h": area_h,
                "off_x": off_x, "off_y": off_y,
                "phys_w": phys_w, "phys_h": phys_h}

    def start_doc(self, name):
        info = DOCINFOW()
        info.cbSize = ctypes.sizeof(DOCINFOW)
        info.lpszDocName = (name or "Document")[:200]
        info.lpszOutput = None
        info.lpszDatatype = None
        info.fwType = 0
        job_id = gdi32.StartDocW(self.hdc, ctypes.byref(info))
        if job_id <= 0:
            raise PrintError("the spooler refused the job (error %d)"
                             % ctypes.get_last_error())
        self._doc_open = True
        self.job_id = job_id        # the number Devices and Printers shows
        return job_id

    def _header(self, raster, top_down=True):
        head = BITMAPINFOHEADER()
        head.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        head.biWidth = raster.width
        head.biHeight = -raster.height if top_down else raster.height
        head.biPlanes = 1
        head.biBitCount = 32
        head.biCompression = BI_RGB
        head.biSizeImage = 0
        return head

    def _send(self, raster, x, y, w, h, buffer, top_down):
        head = self._header(raster, top_down)
        gdi32.SetStretchBltMode(self.hdc, STRETCH_MODE)
        gdi32.SetBrushOrgEx(self.hdc, 0, 0, None)
        rows = gdi32.StretchDIBits(
            self.hdc, int(x), int(y), int(w), int(h),
            0, 0, raster.width, raster.height,
            buffer, ctypes.byref(head), DIB_RGB_COLORS, SRCCOPY)
        # StretchDIBits answers with the number of scan lines it took, or
        # GDI_ERROR - which, declared as a signed int, arrives as -1. That is
        # emphatically not "zero lines", so checking for zero alone lets a
        # completely failed page be reported as printed.
        if rows in (0, -1, GDI_ERROR):
            return 0, ctypes.get_last_error()
        return rows, 0

    def blit(self, raster, x, y, w, h):
        """Put one rendered page on the current sheet at an exact place."""
        if gdi32.StartPage(self.hdc) <= 0:
            raise PrintError("could not start a page (error %d)"
                             % ctypes.get_last_error())

        rows, err = self._send(raster, x, y, w, h, raster.buffer, True)
        used = "top-down"

        if not rows:
            # Some drivers will not take a top-down DIB and say so only by
            # failing. Turning the rows the other way up costs one copy and is
            # the difference between a blank sheet and a printed one.
            self.log("  ! the driver refused a top-down image (error %d); "
                     "trying it the other way up" % err)
            rows, err = self._send(raster, x, y, w, h, _flip_rows(raster), False)
            used = "bottom-up"
            if rows:
                self.prefer_bottom_up = True

        ended = gdi32.EndPage(self.hdc)
        if not rows:
            raise PrintError("the driver would not take the page "
                             "(StretchDIBits failed, error %d)" % err)
        if ended <= 0:
            raise PrintError("the driver would not finish the page (error %d)"
                             % ctypes.get_last_error())
        if self.debug:
            self.log("    blitted %d rows, %s, at (%d,%d) %dx%d"
                     % (rows, used, x, y, w, h))


def plan_pages(doc, caps, scale="none", pages=None):
    """Work out, without touching the printer, where every page lands.

    Split out from the printing so the arithmetic can be tested on any
    machine - which matters, because the printing itself cannot be.

    In actual-size mode the page is centred on the sheet of paper, so the
    origin has to step back over the margin the printer cannot reach. In the
    fitting modes it is centred on the printable area instead, because there
    is no point fitting a page into space the printer will not use.
    """
    total = len(doc)
    wanted = [p for p in (pages or range(1, total + 1)) if 1 <= p <= total]
    exact = (scale == "none")
    area_w = caps["phys_w"] if exact else caps["area_w"]
    area_h = caps["phys_h"] if exact else caps["area_h"]
    origin_x = -caps["off_x"] if exact else 0
    origin_y = -caps["off_y"] if exact else 0

    plan = []
    for page_no in wanted:
        w_pt, h_pt = doc.page_size(page_no - 1)
        spot = render.place(w_pt, h_pt, area_w, area_h,
                            caps["dpi_x"], caps["dpi_y"], scale)
        plan.append({
            "page": page_no,
            "x": origin_x + spot.x,
            "y": origin_y + spot.y,
            "w": spot.w,
            "h": spot.h,
            "rotate": spot.rotate,
            "scale": spot.scale,
        })
    return plan


def render_dpi(caps, max_dpi=MAX_RENDER_DPI):
    """Rasterise at the printer's own resolution, within reason."""
    return max(72, min(int(caps.get("dpi_x") or 300), int(max_dpi)))


def print_pdf(path, printer, copies=1, pages=None, scale="none", mono=False,
              duplex=False, duplex_edge="long", paper="", label="Document",
              max_dpi=MAX_RENDER_DPI, log=None, debug=False):
    """Print a PDF straight to a Windows printer. Raises PrintError."""
    if not available():
        raise PrintError("native printing is not available on this machine")

    def note(msg):
        if log:
            log(msg)

    with render.Document(path) as doc:
        if not len(doc):
            raise PrintError("that PDF has no pages")

        with PrinterDC(printer, log=note, debug=debug, copies=copies,
                       duplex=duplex, duplex_edge=duplex_edge, mono=mono,
                       paper=paper) as dc:
            caps = dc.caps()
            plan = plan_pages(doc, caps, scale, pages)
            if not plan:
                raise PrintError("no pages left to print after the page range")

            dpi = render_dpi(caps, max_dpi)
            note("  %s: %d page%s at %ddpi, paper %dx%d device px"
                 % (printer, len(plan), "" if len(plan) == 1 else "s",
                    caps["dpi_x"], caps["phys_w"], caps["phys_h"]))

            trouble = describe_printer(printer)
            if trouble:
                note("  ! the printer says: %s" % trouble)

            spooled_id = dc.start_doc(label)
            for step in plan:
                index = step["page"] - 1
                factor = doc.scale_for(index, render.Placement(
                    step["x"], step["y"], step["w"], step["h"], step["rotate"]))
                # never rasterise finer than the printer can mark
                cap = dpi / float(caps["dpi_x"] or dpi)
                with doc.render(index, factor * min(1.0, cap),
                                step["rotate"], grayscale=mono) as raster:
                    dc.blit(raster, step["x"], step["y"], step["w"], step["h"])

    after = describe_printer(printer)
    if after:
        note("  spooler now: %s" % after)
    return len(plan), spooled_id


# ---------------------------------------------------------------------------
# What the spooler thinks is going on
#
# When a job is accepted and no paper appears, the interesting question is not
# what this code did - it is whether the spooler is holding the job and why.
# This asks.
# ---------------------------------------------------------------------------

PRINTER_STATUS = [
    (0x00000001, "paused"),
    (0x00000002, "error"),
    (0x00000008, "paper jam"),
    (0x00000010, "out of paper"),
    (0x00000020, "waiting for a manual feed"),
    (0x00000040, "paper problem"),
    (0x00000080, "offline"),
    (0x00000200, "busy"),
    (0x00000400, "printing"),
    (0x00000800, "output bin full"),
    (0x00001000, "not available"),
    (0x00002000, "waiting"),
    (0x00004000, "processing"),
    (0x00008000, "initialising"),
    (0x00010000, "warming up"),
    (0x00020000, "toner low"),
    (0x00040000, "out of toner"),
    (0x00100000, "needs attention at the printer"),
    (0x00200000, "out of memory"),
    (0x00400000, "a door is open"),
    (0x01000000, "in power save"),
]
PRINTER_ATTRIBUTE_WORK_OFFLINE = 0x00000400


def printer_status(name):
    """(list of plain-English states, number of jobs waiting), or (None, 0)."""
    if not IS_WINDOWS or not name:
        return None, 0

    class PRINTER_INFO_2W(ctypes.Structure):
        _fields_ = [
            ("pServerName", wintypes.LPWSTR), ("pPrinterName", wintypes.LPWSTR),
            ("pShareName", wintypes.LPWSTR), ("pPortName", wintypes.LPWSTR),
            ("pDriverName", wintypes.LPWSTR), ("pComment", wintypes.LPWSTR),
            ("pLocation", wintypes.LPWSTR), ("pDevMode", ctypes.c_void_p),
            ("pSepFile", wintypes.LPWSTR), ("pPrintProcessor", wintypes.LPWSTR),
            ("pDatatype", wintypes.LPWSTR), ("pParameters", wintypes.LPWSTR),
            ("pSecurityDescriptor", ctypes.c_void_p),
            ("Attributes", wintypes.DWORD), ("Priority", wintypes.DWORD),
            ("DefaultPriority", wintypes.DWORD), ("StartTime", wintypes.DWORD),
            ("UntilTime", wintypes.DWORD), ("Status", wintypes.DWORD),
            ("cJobs", wintypes.DWORD), ("AveragePPM", wintypes.DWORD),
        ]

    handle = wintypes.HANDLE()
    try:
        if not winspool.OpenPrinterW(name, ctypes.byref(handle), None):
            return None, 0
    except (OSError, ValueError):
        return None, 0
    try:
        winspool.GetPrinterW.restype = wintypes.BOOL
        winspool.GetPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                         ctypes.c_void_p, wintypes.DWORD,
                                         ctypes.POINTER(wintypes.DWORD)]
        needed = wintypes.DWORD(0)
        winspool.GetPrinterW(handle, 2, None, 0, ctypes.byref(needed))
        if not needed.value:
            return None, 0
        buf = ctypes.create_string_buffer(needed.value)
        if not winspool.GetPrinterW(handle, 2, buf, needed.value,
                                    ctypes.byref(needed)):
            return None, 0
        info = ctypes.cast(buf, ctypes.POINTER(PRINTER_INFO_2W)).contents
        states = [text for bit, text in PRINTER_STATUS if info.Status & bit]
        if info.Attributes & PRINTER_ATTRIBUTE_WORK_OFFLINE:
            states.append("set to 'Use Printer Offline' in Windows")
        return states, int(info.cJobs)
    except (OSError, ValueError, AttributeError):
        return None, 0
    finally:
        try:
            winspool.ClosePrinter(handle)
        except Exception:
            pass


def describe_printer(name):
    """One line about whether this printer is in a fit state to print."""
    states, jobs = printer_status(name)
    if states is None:
        return ""
    bits = []
    if jobs:
        bits.append("%d job%s already waiting" % (jobs, "" if jobs == 1 else "s"))
    if states:
        bits.append(", ".join(states))
    return "; ".join(bits)


# ---------------------------------------------------------------------------
# Getting a stuck printer going again
#
# Some printers - this project was built around one of them - stop drawing
# jobs down after an interrupted one, and then every job after it just piles
# up. The fix is always the same: throw away what is queued and un-pause the
# printer. Doing that from here saves hunting through Devices and Printers.
# ---------------------------------------------------------------------------

PRINTER_CONTROL_RESUME, PRINTER_CONTROL_PURGE = 2, 3
PRINTER_ACCESS_ADMINISTER, PRINTER_ACCESS_USE = 0x0004, 0x0008
STANDARD_RIGHTS_REQUIRED = 0x000F0000
PRINTER_ALL_ACCESS = (STANDARD_RIGHTS_REQUIRED | PRINTER_ACCESS_ADMINISTER
                      | PRINTER_ACCESS_USE)


def clear_queue(printer, log=None):
    """Cancel everything waiting and take the printer off pause.

    Returns (ok, message). Never raises - this is a recovery path, and a
    recovery path that throws is no help to anybody.
    """
    def say(msg):
        if log:
            log(msg)

    if not IS_WINDOWS or not printer:
        return False, "only Windows printers can be cleared from here"

    if ctypes is None:
        return False, "no Windows API available"

    class PRINTER_DEFAULTSW(ctypes.Structure):
        _fields_ = [("pDatatype", wintypes.LPWSTR),
                    ("pDevMode", ctypes.c_void_p),
                    ("DesiredAccess", wintypes.DWORD)]

    states, jobs = printer_status(printer)
    handle = wintypes.HANDLE()
    defaults = PRINTER_DEFAULTSW(None, None, PRINTER_ALL_ACCESS)
    try:
        opened = winspool.OpenPrinterW(printer, ctypes.byref(handle),
                                       ctypes.byref(defaults))
    except (OSError, ValueError):
        opened = False
    if not opened:
        return False, ("could not take charge of %s - try running Print Bridge "
                       "as administrator" % printer)
    try:
        winspool.SetPrinterW.restype = wintypes.BOOL
        winspool.SetPrinterW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                         ctypes.c_void_p, wintypes.DWORD]
        purged = bool(winspool.SetPrinterW(handle, 0, None, PRINTER_CONTROL_PURGE))
        resumed = bool(winspool.SetPrinterW(handle, 0, None, PRINTER_CONTROL_RESUME))
    except (OSError, ValueError, AttributeError) as e:
        return False, "the spooler refused: %s" % e
    finally:
        try:
            winspool.ClosePrinter(handle)
        except Exception:
            pass

    if not purged and not resumed:
        return False, "the spooler would not clear the queue"

    was = "%d job%s" % (jobs, "" if jobs == 1 else "s") if jobs else "nothing"
    say("  cleared the queue on %s (%s was waiting)" % (printer, was))
    if states:
        say("  the printer still reports: %s" % ", ".join(states))
        say("  if it is offline or in error, switch it off and on")
    return True, ("cleared %s from the queue" % was)
