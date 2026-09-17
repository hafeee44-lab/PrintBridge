"""
HTTP front door: IPP for phones, a small JSON API and a web page for browsers.

Both live on the same port. A phone's Print sheet talks IPP to /ipp/print/...;
a browser talks to / and /api/... . Nothing here is exposed beyond the LAN.
"""

from __future__ import annotations

import base64
import hmac
import io
import json
import os
import posixpath
import socket
import socketserver
import tempfile
import threading
import time
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import __version__, escl, icons, ipp, model, render, scan, urf, winprint
from .ipp import IppError

struct_error = __import__("struct").error

MAX_JOB_BYTES = 200 * 1024 * 1024
MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".png": "image/png",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".webmanifest": "application/manifest+json",
}


def detect_format(head, declared=""):
    if head.startswith(b"%PDF"):
        return "application/pdf"
    if head.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if head.startswith(b"\x89PNG"):
        return "image/png"
    if head.startswith(b"UNIRAST"):
        return "image/urf"                       # Apple Raster, from an iPhone
    if head.startswith(b"RaS2") or head.startswith(b"2SaR"):
        return "image/pwg-raster"
    if head.startswith(b"\x1f\x8b"):
        return "application/gzip"
    if declared and declared != "application/octet-stream":
        return declared
    return "application/octet-stream"


# ---------------------------------------------------------------------------
# request body: content-length or chunked, streamed
# ---------------------------------------------------------------------------

class BodyReader:
    def __init__(self, rfile, headers):
        te = (headers.get("Transfer-Encoding") or "").lower()
        self.rfile = rfile
        self.chunked = "chunked" in te
        self.remaining = None
        self.done = False
        self._chunk_left = 0
        if not self.chunked:
            try:
                self.remaining = int(headers.get("Content-Length") or 0)
            except ValueError:
                self.remaining = 0
            self.done = self.remaining == 0

    def read(self, n):
        if self.done or n <= 0:
            return b""
        if not self.chunked:
            n = min(n, self.remaining)
            data = self.rfile.read(n)
            self.remaining -= len(data)
            if self.remaining <= 0 or not data:
                self.done = True
            return data

        if self._chunk_left == 0:
            line = self.rfile.readline(1024).strip()
            if not line:
                line = self.rfile.readline(1024).strip()
            size_part = line.split(b";", 1)[0].strip()
            try:
                self._chunk_left = int(size_part or b"0", 16)
            except ValueError:
                self.done = True
                return b""
            if self._chunk_left == 0:                 # terminal chunk
                while True:                            # swallow trailers
                    t = self.rfile.readline(1024)
                    if not t or t in (b"\r\n", b"\n"):
                        break
                self.done = True
                return b""
        take = min(n, self._chunk_left)
        data = self.rfile.read(take)
        self._chunk_left -= len(data)
        if self._chunk_left == 0:
            self.rfile.read(2)                         # trailing CRLF
        if not data:
            self.done = True
        return data

    def drain(self, limit=4 * 1024 * 1024):
        seen = 0
        while not self.done and seen < limit:
            chunk = self.read(65536)
            if not chunk:
                break
            seen += len(chunk)
        return self.done

    def spool(self, fh, limit=MAX_JOB_BYTES):
        """Stream what is left into a file. Returns (bytes, head, overflow)."""
        total = 0
        head = b""
        overflow = False
        while True:
            chunk = self.read(262144)
            if not chunk:
                break
            if len(head) < 16:
                head += chunk[:16 - len(head)]
            total += len(chunk)
            if total > limit:
                overflow = True
                break
            fh.write(chunk)
        return total, head, overflow


# ---------------------------------------------------------------------------
# the service: a set of queues plus the operations over them
# ---------------------------------------------------------------------------

class Service:
    def __init__(self, backend, spool_dir, pin="", log=print,
                 max_bytes=MAX_JOB_BYTES):
        self.backend = backend
        self.spool_dir = spool_dir
        self.pin = pin or ""
        self.log = log
        self.max_bytes = max_bytes
        self.queues = []
        os.makedirs(spool_dir, exist_ok=True)
        self.sweep_spool()

        # scanning. There is one piece of glass, so one scan at a time.
        self.scanner = None
        self.scanner_checked = False
        self.scan_lock = threading.Lock()
        self.scan_pages = []          # [(jpeg bytes, dpi)] for the web page
        self.scan_jobs = {}           # eSCL jobs, newest kept

    def find_scanner(self, refresh=False):
        if refresh or not self.scanner_checked:
            self.scanner = scan.default_scanner()
            self.scanner_checked = True
        return self.scanner

    def scan_once(self, dpi, mode):
        """One page off the glass, as JPEG bytes. Returns (bytes, ScanResult)."""
        scanner = self.find_scanner()
        if scanner is None:
            return None, scan.ScanResult(False, detail="no scanner is connected")
        with self.scan_lock:
            result = scan.scan_page(scanner.device_id, dpi, mode,
                                    out_dir=self.spool_dir)
        if not result.ok:
            return None, result
        try:
            with open(result.path, "rb") as fh:
                data = fh.read()
        except OSError as e:
            return None, scan.ScanResult(False, detail="could not read the scan: %s" % e)
        finally:
            try:
                os.unlink(result.path)
            except OSError:
                pass
        return data, result

    def sweep_spool(self, older_than=6 * 3600):
        """Throw away spool files left behind by jobs that never finished.

        A client that opens a job and then vanishes leaves its half-received
        document on disk with nothing pointing at it. One sweep at startup
        keeps the folder from growing quietly forever.
        """
        cutoff = time.time() - older_than
        removed = 0
        try:
            names = os.listdir(self.spool_dir)
        except OSError:
            return 0
        for name in names:
            if not name.startswith(("pbjob-", "pbscan-")):
                continue
            path = os.path.join(self.spool_dir, name)
            try:
                if os.path.getmtime(path) < cutoff:
                    os.unlink(path)
                    removed += 1
            except OSError:
                pass
        if removed:
            self.log("  tidied %d leftover spool file%s"
                     % (removed, "" if removed == 1 else "s"))
        return removed

    def add_queue(self, q):
        self.queues.append(q)
        return q

    @property
    def default_queue(self):
        return self.queues[0] if self.queues else None

    def lookup(self, path, printer_uri=""):
        path = (path or "/").split("?")[0].rstrip("/").lower() or "/"
        for q in self.queues:
            if q.resource.rstrip("/").lower() == path:
                return q
        if printer_uri:
            tail = urllib.parse.urlparse(printer_uri).path.rstrip("/").lower()
            for q in self.queues:
                if q.resource.rstrip("/").lower() == tail:
                    return q
        return self.default_queue

    def set_host(self, host, port):
        for q in self.queues:
            q.set_host(host, port)

    def shutdown(self):
        for q in self.queues:
            q.shutdown()


# ---------------------------------------------------------------------------
# IPP operation handling
# ---------------------------------------------------------------------------

SUPPORTED_VERSIONS = ((1, 0), (1, 1), (2, 0))

# operations that address the printer itself and therefore need printer-uri
PRINTER_OPS = (
    ipp.OP_PRINT_JOB, ipp.OP_VALIDATE_JOB, ipp.OP_CREATE_JOB,
    ipp.OP_GET_JOBS, ipp.OP_GET_PRINTER_ATTRIBUTES, ipp.OP_IDENTIFY_PRINTER,
)


def _validate_operation_attrs(req):
    """RFC 8011 4.1.4: charset first, language second, then a target URI."""
    group = req.groups[0] if req.groups else None
    if group is None or group.tag != ipp.TAG_OPERATION or not group.attrs:
        return "the operation attributes group is missing"
    names = [a.name for a in group.attrs]
    if names[0] != "attributes-charset":
        return "attributes-charset must come first"
    if len(names) < 2 or names[1] != "attributes-natural-language":
        return "attributes-natural-language must come second"
    if req.operation in PRINTER_OPS and not group.value("printer-uri"):
        return "printer-uri is required"
    if req.operation == ipp.OP_CANCEL_MY_JOBS and not group.value("printer-uri"):
        return "printer-uri is required"
    if req.operation in (ipp.OP_SEND_DOCUMENT, ipp.OP_CANCEL_JOB,
                         ipp.OP_GET_JOB_ATTRIBUTES, ipp.OP_CLOSE_JOB):
        if not group.value("job-uri") and group.value("job-id") is None:
            return "job-uri or printer-uri plus job-id is required"
    return None


def _base_response(req, status, message=""):
    version = req.version if req.version[0] <= 2 else (2, 0)
    msg = ipp.Message(version, status, req.request_id)
    g = msg.add_group(ipp.Group(ipp.TAG_OPERATION))
    g.add(ipp.charset("attributes-charset", "utf-8"))
    g.add(ipp.language("attributes-natural-language", "en"))
    if message:
        g.add(ipp.text("status-message", message))
    return msg


def _job_options(job, job_group):
    """Translate IPP job-template attributes into backend options."""
    copies = job_group.value("copies", 1)
    try:
        job.copies = max(1, min(99, int(copies)))
    except (TypeError, ValueError):
        job.copies = 1

    scaling = (job_group.value("print-scaling") or "").lower()
    if scaling in ("none",):
        job.scale = "none"
    elif scaling in ("fit", "fill", "auto-fit"):
        job.scale = "fit"
    else:
        job.scale = "auto"

    colour = (job_group.value("print-color-mode") or "").lower()
    job.mono = colour != "color"

    sides = (job_group.value("sides") or "one-sided").lower()
    job.duplex = sides.startswith("two-sided")
    job.duplex_edge = "short" if "short" in sides else "long"

    media = (job_group.value("media") or "").lower()
    if "a4" in media:
        job.media = "A4"
    elif "letter" in media:
        job.media = "letter"
    elif "legal" in media:
        job.media = "legal"
    elif "a5" in media:
        job.media = "A5"

    ranges = job_group.get("page-ranges")
    if ranges and ranges.values:
        parts = []
        for r in ranges.values:
            if isinstance(r, ipp.IntRange):
                parts.append("%d-%d" % (r.lower, r.upper)
                             if r.lower != r.upper else "%d" % r.lower)
        job.pages = ",".join(parts)


class IppHandlerMixin:
    """Mixed into the HTTP handler; keeps the IPP logic in one place."""

    def ipp_dispatch(self, path, reader):
        service = self.server.service
        try:
            req = ipp.decode(reader)
        except IppError as e:
            self.send_ipp(_base_response(ipp.Message(), e.status, e.message))
            return
        except Exception as e:
            self.send_ipp(_base_response(ipp.Message(), ipp.ERR_BAD_REQUEST, str(e)))
            return

        if req.request_id == 0:
            # RFC 8011 4.1.1: request-id must be 1..2^31-1
            reader.drain()
            self.send_ipp(_base_response(req, ipp.ERR_BAD_REQUEST,
                                         "request-id must not be zero"))
            return

        op = req.operation
        opname = ipp.OP_NAMES.get(op, "0x%04x" % op)
        ua = self.headers.get("User-Agent", "")
        service.log("  ipp %-24s %s  %s" % (opname, path, ua[:40]))

        if req.version not in SUPPORTED_VERSIONS:
            reader.drain()
            self.send_ipp(_base_response(req, ipp.ERR_VERSION_NOT_SUPPORTED,
                                         "this printer speaks IPP 1.0, 1.1 "
                                         "and 2.0"))
            return

        problem = _validate_operation_attrs(req)
        if problem:
            reader.drain()
            self.send_ipp(_base_response(req, ipp.ERR_BAD_REQUEST, problem))
            return

        printer_uri = req.op_attrs.value("printer-uri", "")
        queue = service.lookup(path, printer_uri)
        if queue is None:
            self.send_ipp(_base_response(req, ipp.ERR_NOT_FOUND,
                                         "no printers are shared"))
            reader.drain()
            return

        try:
            handler = {
                ipp.OP_GET_PRINTER_ATTRIBUTES: self._op_get_printer_attrs,
                ipp.OP_VALIDATE_JOB: self._op_validate,
                ipp.OP_PRINT_JOB: self._op_print_job,
                ipp.OP_CREATE_JOB: self._op_create_job,
                ipp.OP_SEND_DOCUMENT: self._op_send_document,
                ipp.OP_CLOSE_JOB: self._op_close_job,
                ipp.OP_CANCEL_JOB: self._op_cancel_job,
                ipp.OP_CANCEL_MY_JOBS: self._op_cancel_my_jobs,
                ipp.OP_GET_JOB_ATTRIBUTES: self._op_get_job_attrs,
                ipp.OP_GET_JOBS: self._op_get_jobs,
                ipp.OP_IDENTIFY_PRINTER: self._op_identify,
            }.get(op)
            if handler is None:
                reader.drain()
                self.send_ipp(_base_response(
                    req, ipp.ERR_OPERATION_NOT_SUPPORTED,
                    "%s is not supported" % opname))
                return
            response = handler(req, queue, reader)
        except IppError as e:
            reader.drain()
            response = _base_response(req, e.status, e.message)
        except Exception as e:                       # never 500 on a phone
            service.log("  ! %s while handling %s: %s"
                        % (type(e).__name__, opname, e))
            reader.drain()
            response = _base_response(req, ipp.ERR_INTERNAL, str(e))

        self.send_ipp(response)

    # -- operations ---------------------------------------------------------
    def _op_get_printer_attrs(self, req, queue, reader):
        reader.drain()
        requested = req.op_attrs.values("requested-attributes") or ["all"]
        msg = _base_response(req, ipp.OK)
        msg.groups.append(queue.printer_attrs(requested))
        return msg

    def _check_format(self, req, queue):
        fmt = (req.op_attrs.value("document-format") or "").lower()
        if fmt and fmt not in model.FORMATS:
            raise IppError(ipp.ERR_FORMAT_NOT_SUPPORTED,
                           "%s is not supported; send PDF" % fmt)
        return fmt or "application/pdf"

    def _op_validate(self, req, queue, reader):
        reader.drain()
        self._check_format(req, queue)
        return _base_response(req, ipp.OK)

    def _new_job(self, req, queue):
        fmt = self._check_format(req, queue)
        name = req.op_attrs.value("job-name") or "Untitled"
        user = req.op_attrs.value("requesting-user-name") or "phone"
        job = queue.new_job(str(name)[:120], str(user)[:60], fmt)
        _job_options(job, req.job_attrs)
        return job

    def _receive_document(self, job, queue, reader, declared=""):
        fd, path = tempfile.mkstemp(prefix="pbjob-", suffix=".dat",
                                    dir=self.server.service.spool_dir)
        total = head = None
        with os.fdopen(fd, "wb") as fh:
            total, head, overflow = reader.spool(fh, self.server.service.max_bytes)
        if overflow:
            os.unlink(path)
            queue.cancel(job)
            raise IppError(ipp.ERR_TOO_LARGE, "job is larger than the limit")
        if total == 0:
            os.unlink(path)
            return 0
        fmt = detect_format(head, declared or job.format)

        if fmt == "image/pwg-raster":
            os.unlink(path)
            job.state = model.ABORTED
            job.reasons = ["document-format-error"]
            job.detail = "PWG raster received; this bridge takes PDF or Apple Raster"
            raise IppError(ipp.ERR_FORMAT_NOT_SUPPORTED,
                           "send PDF or Apple Raster, not PWG raster")

        if fmt == "image/urf":
            # An iPhone rendered the page itself. Turn it back into a PDF so
            # the printer's own driver can do the rest.
            pdf_path = path[:-4] + ".pdf"
            try:
                pages = urf.convert_file(path, pdf_path)
            except (urf.UrfError, MemoryError, struct_error) as e:
                os.unlink(path)
                job.state = model.ABORTED
                job.reasons = ["document-format-error"]
                job.detail = "could not read the Apple Raster job: %s" % e
                raise IppError(ipp.ERR_DOCUMENT_FORMAT_ERROR, str(e))
            os.unlink(path)
            self.server.service.log(
                "  converted Apple Raster from the phone: %d page%s"
                % (pages, "" if pages == 1 else "s"))
            job.format = "application/pdf"
            job.path = pdf_path
            job.size = os.path.getsize(pdf_path)
            job.impressions = pages
            # the phone already laid the page out at its exact size
            job.scale = "none"
            return total

        job.format = fmt
        ext = {"application/pdf": ".pdf", "image/jpeg": ".jpg",
               "image/png": ".png"}.get(fmt, ".bin")
        final = path[:-4] + ext
        os.replace(path, final)
        job.path = final
        job.size = total
        return total

    def _op_print_job(self, req, queue, reader):
        job = self._new_job(req, queue)
        declared = (req.op_attrs.value("document-format") or "").lower()
        total = self._receive_document(job, queue, reader, declared)
        if total == 0:
            queue.cancel(job)
            raise IppError(ipp.ERR_BAD_REQUEST, "no document data")
        queue.submit(job)
        msg = _base_response(req, ipp.OK)
        msg.groups.append(job.attrs(
            ["job-uri", "job-id", "job-state", "job-state-reasons",
             "job-state-message"], queue.up_time()))
        return msg

    def _op_create_job(self, req, queue, reader):
        reader.drain()
        job = self._new_job(req, queue)
        msg = _base_response(req, ipp.OK)
        msg.groups.append(job.attrs(
            ["job-uri", "job-id", "job-state", "job-state-reasons"],
            queue.up_time()))
        return msg

    def _find_job(self, req, queue):
        jid = req.op_attrs.value("job-id")
        if jid is None:
            juri = req.op_attrs.value("job-uri") or ""
            tail = juri.rstrip("/").rsplit("/", 1)[-1]
            try:
                jid = int(tail)
            except (TypeError, ValueError):
                jid = None
        if jid is None:
            raise IppError(ipp.ERR_BAD_REQUEST, "no job-id given")
        job = queue.find_job(int(jid))
        if job is None:
            raise IppError(ipp.ERR_NOT_FOUND, "no such job")
        return job

    def _op_send_document(self, req, queue, reader):
        job = self._find_job(req, queue)
        declared = (req.op_attrs.value("document-format") or "").lower()
        if req.op_attrs.get("last-document") is None:
            # RFC 8011 4.3.1 makes this one mandatory
            reader.drain()
            raise IppError(ipp.ERR_BAD_REQUEST, "last-document is required")
        last = req.op_attrs.value("last-document", True)
        self._receive_document(job, queue, reader, declared)
        if last:
            if not job.path:
                queue.cancel(job)
                raise IppError(ipp.ERR_BAD_REQUEST, "no document data")
            queue.submit(job)
        msg = _base_response(req, ipp.OK)
        msg.groups.append(job.attrs(
            ["job-uri", "job-id", "job-state", "job-state-reasons"],
            queue.up_time()))
        return msg

    def _op_close_job(self, req, queue, reader):
        reader.drain()
        job = self._find_job(req, queue)
        if job.path:
            queue.submit(job)
        msg = _base_response(req, ipp.OK)
        msg.groups.append(job.attrs(
            ["job-uri", "job-id", "job-state", "job-state-reasons"],
            queue.up_time()))
        return msg

    def _op_cancel_job(self, req, queue, reader):
        reader.drain()
        job = self._find_job(req, queue)
        if not queue.cancel(job):
            raise IppError(ipp.ERR_NOT_POSSIBLE, "job already finished")
        return _base_response(req, ipp.OK)

    def _op_cancel_my_jobs(self, req, queue, reader):
        reader.drain()
        user = req.op_attrs.value("requesting-user-name") or ""
        wanted = req.op_attrs.values("job-ids")
        for job in list(queue.jobs):
            if wanted and job.id not in wanted:
                continue
            if not wanted and user and job.user != user:
                continue
            queue.cancel(job)
        return _base_response(req, ipp.OK)

    def _op_get_job_attrs(self, req, queue, reader):
        reader.drain()
        job = self._find_job(req, queue)
        requested = req.op_attrs.values("requested-attributes") or ["all"]
        msg = _base_response(req, ipp.OK)
        msg.groups.append(job.attrs(requested, queue.up_time()))
        return msg

    def _op_get_jobs(self, req, queue, reader):
        reader.drain()
        which = (req.op_attrs.value("which-jobs") or "not-completed").lower()
        limit = req.op_attrs.value("limit") or 0
        # RFC 8011 4.2.6: with no requested-attributes, send only the two
        # identifying ones - not the whole job object.
        requested = req.op_attrs.values("requested-attributes") or ["job-uri",
                                                                    "job-id"]
        finished = (model.COMPLETED, model.CANCELED, model.ABORTED)
        jobs = list(queue.jobs)
        if which == "completed":
            jobs = [j for j in jobs if j.state in finished]
        elif which != "all":
            jobs = [j for j in jobs if j.state not in finished]
        jobs.reverse()
        if limit:
            jobs = jobs[:int(limit)]
        msg = _base_response(req, ipp.OK)
        for j in jobs:
            msg.groups.append(j.attrs(requested, queue.up_time()))
        return msg

    def _op_identify(self, req, queue, reader):
        reader.drain()
        self.server.service.log("  >> a device is asking 'is this you?' "
                                "-> %s" % queue.printer_name)
        return _base_response(req, ipp.OK)


# ---------------------------------------------------------------------------
# the HTTP handler
# ---------------------------------------------------------------------------

class Handler(IppHandlerMixin, BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "PrintBridge/" + __version__
    timeout = 300
    sys_version = ""

    # -- plumbing -----------------------------------------------------------
    def log_message(self, fmt, *args):
        pass

    def log_error(self, fmt, *args):
        pass

    def send_bytes(self, code, ctype, body, extra=None, cache=False):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if cache:
            self.send_header("Cache-Control", "public, max-age=86400")
        else:
            self.send_header("Cache-Control", "no-store")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_xml(self, body, code=200):
        self.send_bytes(code, "text/xml; charset=utf-8", body.encode("utf-8"))

    def send_json(self, obj, code=200):
        self.send_bytes(code, "application/json; charset=utf-8",
                        json.dumps(obj).encode("utf-8"))

    def send_ipp(self, msg):
        try:
            body = ipp.encode(msg)
        except Exception as e:
            self.server.service.log("  ! could not encode response: %s" % e)
            body = ipp.encode(ipp.Message((1, 1), ipp.ERR_INTERNAL,
                                          msg.request_id))
        self.send_bytes(200, "application/ipp", body)

    def _authorised(self):
        pin = self.server.service.pin
        if not pin:
            return True
        auth = self.headers.get("Authorization", "")
        if auth.lower().startswith("basic "):
            try:
                raw = base64.b64decode(auth.split(None, 1)[1]).decode("utf-8")
                if hmac.compare_digest(raw.split(":", 1)[-1], pin):
                    return True
            except Exception:
                pass
        if hmac.compare_digest(self.headers.get("X-Print-Pin", ""), pin):
            return True
        q = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        return hmac.compare_digest(q.get("pin", [""])[0], pin)

    # -- routing ------------------------------------------------------------
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip()
        reader = BodyReader(self.rfile, self.headers)

        if ctype == "application/ipp":
            if not self._authorised():
                reader.drain()
                self.send_response(401)
                self.send_header("WWW-Authenticate",
                                 'Basic realm="PrintBridge"')
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            self.ipp_dispatch(path, reader)
            if not reader.done:
                reader.drain()
            return

        if path == "/api/print":
            self.api_print(parsed, reader)
            return

        if path == "/api/scan":
            reader.drain()
            self.api_scan(parsed)
            return
        if path == "/api/printer/clear":
            reader.drain()
            if not self._authorised():
                self.send_json({"ok": False, "error": "PIN required"}, 401)
                return
            wanted = urllib.parse.parse_qs(parsed.query).get("printer", [""])[0]
            queue = None
            for x in self.server.service.queues:
                if x.printer_name == wanted:
                    queue = x
                    break
            queue = queue or self.server.service.default_queue
            if queue is None:
                self.send_json({"ok": False, "error": "no printers"}, 503)
                return
            ok, detail = winprint.clear_queue(queue.printer_name,
                                              log=self.server.service.log)
            self.send_json({"ok": ok, "detail": detail,
                            "trouble": winprint.describe_printer(queue.printer_name)},
                           200 if ok else 500)
            return
        if path == "/api/scan/clear":
            reader.drain()
            self.server.service.scan_pages = []
            self.send_json({"ok": True, "pages": 0})
            return
        if path == "/eSCL/ScanJobs":
            self.escl_create_job(reader)
            return

        reader.drain()
        self.send_json({"error": "not found"}, 404)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = posixpath.normpath(urllib.parse.unquote(parsed.path))
        service = self.server.service

        if path.startswith("/icons/"):
            name = path.rsplit("/", 1)[-1]
            try:
                size = int(name.replace("printer-", "").replace(".png", ""))
            except ValueError:
                size = 128
            self.send_bytes(200, "image/png", icons.get(min(512, max(16, size))),
                            cache=True)
            return

        if path == "/api/hello":
            self.send_json(self.hello())
            return
        if path == "/api/printers":
            d = service.default_queue
            self.send_json({
                "ok": True,
                "printers": [
                    {"name": q.printer_name,
                     "status": "Idle" if q.state == 3 else "Busy",
                     "isDefault": q is d,
                     "queued": len(q.active_jobs()),
                     "trouble": winprint.describe_printer(q.printer_name)}
                    for q in service.queues
                ],
                "default": d.printer_name if d else None,
            })
            return
        if path == "/api/scanners":
            found = service.find_scanner(refresh=("refresh" in (parsed.query or "")))
            self.send_json({"ok": True,
                            "scanner": found.as_dict() if found else None,
                            "pages": len(service.scan_pages)})
            return
        if path.startswith("/api/scan/page/"):
            try:
                index = int(path.rsplit("/", 1)[-1].split(".")[0])
            except ValueError:
                index = -1
            if 0 <= index < len(service.scan_pages):
                self.send_bytes(200, "image/jpeg", service.scan_pages[index][0])
            else:
                self.send_bytes(404, "text/plain; charset=utf-8", b"no such page\n")
            return
        if path == "/api/scan/pdf":
            pdf = render.images_to_pdf(service.scan_pages)
            if not pdf:
                self.send_json({"ok": False, "error": "nothing scanned yet"}, 404)
                return
            self.send_bytes(200, "application/pdf", pdf, extra={
                "Content-Disposition": 'attachment; filename="scan.pdf"'})
            return

        if path == "/eSCL/ScannerCapabilities":
            found = service.find_scanner()
            if found is None:
                self.send_bytes(503, "text/plain; charset=utf-8", b"no scanner\n")
                return
            self.send_xml(escl.capabilities_xml(found))
            return
        if path == "/eSCL/ScannerStatus":
            busy = service.scan_lock.locked()
            self.send_xml(escl.status_xml("Processing" if busy else "Idle",
                                          list(service.scan_jobs.values())))
            return
        if path.startswith("/eSCL/ScanJobs/"):
            self.escl_next_document(path)
            return

        if path == "/api/jobs":
            jobs = []
            for q in service.queues:
                for j in reversed(q.jobs[-40:]):
                    d = j.as_dict()
                    d["printer"] = q.printer_name
                    jobs.append(d)
            self.send_json({"jobs": jobs})
            return

        # IPP clients sometimes probe the queue URL with GET
        for q in service.queues:
            if path.rstrip("/").lower() == q.resource.rstrip("/").lower():
                self.send_bytes(
                    200, "text/plain; charset=utf-8",
                    ("%s\nIPP endpoint. Point a phone at it, not a browser.\n"
                     % q.printer_name).encode("utf-8"))
                return

        self.serve_static(path)

    def do_HEAD(self):
        self.do_GET()

    # -- web app ------------------------------------------------------------
    def hello(self):
        service = self.server.service
        q = service.default_queue
        method = service.backend.method
        return {
            "server": "print-bridge",
            "version": __version__,
            "host": self.server.advertised_host,
            "port": self.server.server_address[1],
            "needsPin": bool(service.pin),
            "helper": {"native": "native", "sumatrapdf": "sumatra",
                       "simulate": "simulate"}.get(method, "fallback"),
            "helperDetail": service.backend.method_detail,
            "simulate": service.backend.simulate,
            "airprint": {
                "advertised": bool(self.server.airprint_names),
                "names": self.server.airprint_names,
                "uri": q.uri if q else None,
            },
            "queues": [
                {"name": x.printer_name, "resource": x.resource,
                 "uri": x.uri, "jobs": len(x.active_jobs())}
                for x in service.queues
            ],
            "default": q.printer_name if q else None,
        }

    def serve_static(self, path):
        root = self.server.web_dir
        if path in ("/", ""):
            path = "/index.html"
        root = os.path.normpath(root)
        target = os.path.normpath(os.path.join(root, path.lstrip("/")))
        inside = target == root or target.startswith(root + os.sep)
        if not inside or not os.path.isfile(target):
            self.send_bytes(404, "text/plain; charset=utf-8", b"not found\n")
            return
        ext = os.path.splitext(target)[1].lower()
        with open(target, "rb") as fh:
            body = fh.read()
        self.send_bytes(200, MIME_TYPES.get(ext, "application/octet-stream"), body)

    # -- scanning --------------------------------------------------------
    def api_scan(self, parsed):
        """One page off the glass, kept in memory for the web page."""
        service = self.server.service
        if not self._authorised():
            self.send_json({"ok": False, "error": "PIN required"}, 401)
            return
        query = urllib.parse.parse_qs(parsed.query)

        def one(key, default=""):
            return query.get(key, [default])[0]

        try:
            dpi = int(one("dpi", "300"))
        except ValueError:
            dpi = 300
        mode = one("mode", "color")

        if service.scan_lock.locked():
            self.send_json({"ok": False, "error": "a scan is already running"}, 409)
            return

        data, result = service.scan_once(dpi, mode)
        if not data:
            service.log("  scan failed: %s" % result.detail)
            self.send_json({"ok": False, "error": result.detail}, 500)
            return

        service.scan_pages.append((data, result.dpi or dpi))
        index = len(service.scan_pages) - 1
        service.log("  scanned page %d (%dx%d at %ddpi, %.0f KB)"
                    % (index + 1, result.width, result.height, result.dpi,
                       len(data) / 1024.0))
        self.send_json({
            "ok": True, "index": index, "pages": len(service.scan_pages),
            "width": result.width, "height": result.height, "dpi": result.dpi,
            "widthMm": round(result.width / float(result.dpi or dpi) * 25.4, 1),
            "heightMm": round(result.height / float(result.dpi or dpi) * 25.4, 1),
            "url": "/api/scan/page/%d.jpg" % index,
        })

    # -- eSCL ------------------------------------------------------------
    def escl_create_job(self, reader):
        """A phone asks for a scan. Accept it and let NextDocument do the work."""
        service = self.server.service
        body = b""
        while True:
            chunk = reader.read(65536)
            if not chunk:
                break
            body += chunk
            if len(body) > 256 * 1024:
                break

        if service.find_scanner() is None:
            self.send_bytes(503, "text/plain; charset=utf-8", b"no scanner\n")
            return

        settings = escl.parse_scan_settings(body)
        job = escl.ScanJob(settings["dpi"], settings["mode"], settings["format"])
        # keep the last few jobs only; clients poll the one they just made
        if len(service.scan_jobs) > 8:
            oldest = sorted(service.scan_jobs.values(), key=lambda j: j.created)[0]
            service.scan_jobs.pop(oldest.job_id, None)
        service.scan_jobs[job.job_id] = job
        service.log("  eSCL scan job %s: %ddpi %s %s"
                    % (job.job_id, job.dpi, job.mode, job.format))

        host = self.headers.get("Host") or ("%s:%d" % (self.server.advertised_host,
                                                       self.server.server_address[1]))
        self.send_bytes(201, "text/plain; charset=utf-8", b"", extra={
            "Location": "http://%s/eSCL/ScanJobs/%s" % (host, job.job_id)})

    def escl_next_document(self, path):
        """The page itself. The scan happens here, because this is what waits."""
        service = self.server.service
        parts = [p for p in path.split("/") if p]
        # /eSCL/ScanJobs/<id>/NextDocument
        if len(parts) < 3:
            self.send_bytes(404, "text/plain; charset=utf-8", b"no such job\n")
            return
        job_id = parts[2]
        job = service.scan_jobs.get(job_id)
        if job is None:
            self.send_bytes(404, "text/plain; charset=utf-8", b"no such job\n")
            return
        if len(parts) < 4 or parts[3].lower() != "nextdocument":
            self.send_bytes(404, "text/plain; charset=utf-8", b"not found\n")
            return

        with job.lock:
            if job.delivered:
                # one page per job from a flatbed; say there is no more
                job.state = "Completed"
                job.reason = "JobCompletedSuccessfully"
                self.send_bytes(404, "text/plain; charset=utf-8", b"no more pages\n")
                return

            job.state = "Processing"
            job.reason = "JobScanning"
            data, result = service.scan_once(job.dpi, job.mode)
            if not data:
                job.state = "Aborted"
                job.reason = "JobScanningAndTransferring"
                service.log("  eSCL scan failed: %s" % result.detail)
                self.send_bytes(503, "text/plain; charset=utf-8",
                                result.detail.encode("utf-8"))
                return

            job.delivered = 1
            job.state = "Completed"
            job.reason = "JobCompletedSuccessfully"

        if job.format == "application/pdf":
            pdf = render.images_to_pdf([(data, result.dpi or job.dpi)])
            if pdf:
                service.log("  eSCL delivered a PDF (%.0f KB)" % (len(pdf)/1024.0))
                self.send_bytes(200, "application/pdf", pdf)
                return
        service.log("  eSCL delivered a JPEG (%.0f KB)" % (len(data)/1024.0))
        self.send_bytes(200, "image/jpeg", data)

    def do_DELETE(self):
        path = urllib.parse.urlparse(self.path).path
        if path.startswith("/eSCL/ScanJobs/"):
            job_id = path.rstrip("/").rsplit("/", 1)[-1]
            self.server.service.scan_jobs.pop(job_id, None)
            self.send_bytes(200, "text/plain; charset=utf-8", b"")
            return
        self.send_bytes(404, "text/plain; charset=utf-8", b"not found\n")

    def api_print(self, parsed, reader):
        service = self.server.service
        if not self._authorised():
            reader.drain()
            self.send_json({"ok": False, "error": "PIN required"}, 401)
            return

        q = urllib.parse.parse_qs(parsed.query)

        def one(key, default=""):
            return q.get(key, [default])[0]

        queue = None
        wanted = one("printer")
        for x in service.queues:
            if x.printer_name == wanted:
                queue = x
                break
        queue = queue or service.default_queue
        if queue is None:
            reader.drain()
            self.send_json({"ok": False, "error": "no printers"}, 503)
            return

        label = one("label", "document.pdf")[:120]
        job = queue.new_job(label, "browser", "application/pdf")
        try:
            job.copies = max(1, min(99, int(one("copies", "1") or 1)))
        except ValueError:
            job.copies = 1
        job.pages = one("pages", "")
        scale = one("scale", "none").lower()
        job.scale = {"actual": "none", "none": "none", "noscale": "none",
                     "shrink": "auto", "auto": "auto",
                     "fit": "fit"}.get(scale, "none")
        job.mono = one("mono", "0") not in ("0", "false", "")
        job.media = one("paper", "")
        subset = one("subset", "").lower()
        job.subset = subset if subset in ("odd", "even") else ""
        job.reverse = one("order", "") == "reverse"

        try:
            total = self._receive_document(job, queue, reader)
        except IppError as e:
            self.send_json({"ok": False, "error": e.message}, 400)
            return
        if not total:
            queue.cancel(job)
            self.send_json({"ok": False, "error": "empty upload"}, 400)
            return

        queue.submit(job)
        deadline = time.time() + 240
        while time.time() < deadline and job.state in (model.PENDING,
                                                       model.PROCESSING):
            time.sleep(0.2)
        ok = job.state == model.COMPLETED
        self.send_json({
            "ok": ok, "job": job.id, "state": model.STATE_NAMES.get(job.state),
            "detail": job.detail, "printer": queue.printer_name,
            "bytes": total,
        }, 200 if ok else 502)


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 32

    def __init__(self, addr, service, web_dir, advertised_host="127.0.0.1"):
        super().__init__(addr, Handler)
        self.service = service
        self.web_dir = web_dir
        self.advertised_host = advertised_host
        self.airprint_names = []

    def handle_error(self, request, client_address):
        import sys, traceback
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, BrokenPipeError,
                            socket.timeout, TimeoutError)):
            return
        self.service.log("  ! connection error from %s: %s"
                         % (client_address[0], exc))
