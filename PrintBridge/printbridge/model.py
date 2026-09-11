"""
The printer object an IPP client sees, and the job queue behind it.

One instance of Queue == one thing that shows up in your phone's Print sheet.
"""

from __future__ import annotations

import os
import re
import threading
import time
import uuid as uuidlib

from . import ipp
from .ipp import (
    Attr, Collection, Group, boolean, charset, collection, enum, integer,
    keyword, language, mime, name_, novalue, rangeof, resolution, text, uri,
)

# job states
PENDING = 3
HELD = 4
PROCESSING = 5
STOPPED = 6
CANCELED = 7
ABORTED = 8
COMPLETED = 9

STATE_NAMES = {
    PENDING: "pending", HELD: "pending-held", PROCESSING: "processing",
    STOPPED: "processing-stopped", CANCELED: "canceled", ABORTED: "aborted",
    COMPLETED: "completed",
}

MEDIA = {
    # keyword: (width, height) in hundredths of a millimetre
    "iso_a4_210x297mm":    (21000, 29700),
    "na_letter_8.5x11in":  (21590, 27940),
    "na_legal_8.5x14in":   (21590, 35560),
    "iso_a5_148x210mm":    (14800, 21000),
}
MARGIN = 423          # 1/6 inch, about what a small laser can reach

FORMATS = ("application/pdf", "image/urf", "image/jpeg", "image/png",
           "application/octet-stream")

# What an iPhone is told it may send as Apple Raster. Mirrors what CUPS
# advertises for a mono laser: 8-bit grey and sRGB, 300 and 600 dpi.
URF_SUPPORTED = ("V1.4", "CP1", "W8", "SRGB24", "PQ3-4-5", "RS300-600",
                 "DM1", "FN3")

OPERATIONS = (
    ipp.OP_PRINT_JOB, ipp.OP_VALIDATE_JOB, ipp.OP_CREATE_JOB,
    ipp.OP_SEND_DOCUMENT, ipp.OP_CANCEL_JOB, ipp.OP_GET_JOB_ATTRIBUTES,
    ipp.OP_GET_JOBS, ipp.OP_GET_PRINTER_ATTRIBUTES, ipp.OP_CLOSE_JOB,
    ipp.OP_CANCEL_MY_JOBS,
    ipp.OP_IDENTIFY_PRINTER,
)

JOB_TEMPLATE = {
    "copies-default", "copies-supported",
    "finishings-default", "finishings-supported",
    "media-default", "media-supported", "media-ready",
    "media-col-default", "media-col-supported",
    "number-up-default", "number-up-supported",
    "orientation-requested-default", "orientation-requested-supported",
    "output-bin-default", "output-bin-supported",
    "print-color-mode-default", "print-color-mode-supported",
    "print-quality-default", "print-quality-supported",
    "print-scaling-default", "print-scaling-supported",
    "printer-resolution-default", "printer-resolution-supported",
    "sides-default", "sides-supported",
    "job-sheets-default", "job-sheets-supported",
    "page-ranges-supported",
}


def slugify(s):
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-").lower()
    return s or "printer"


def _media_size(media_kw):
    w, h = MEDIA[media_kw]
    size = Collection()
    size["x-dimension"] = integer("x-dimension", w)
    size["y-dimension"] = integer("y-dimension", h)
    return size


def _media_col(media_kw):
    w, h = MEDIA[media_kw]
    size = Collection()
    size["x-dimension"] = integer("x-dimension", w)
    size["y-dimension"] = integer("y-dimension", h)
    c = Collection()
    c["media-size"] = collection("media-size", size)
    c["media-bottom-margin"] = integer("media-bottom-margin", MARGIN)
    c["media-left-margin"] = integer("media-left-margin", MARGIN)
    c["media-right-margin"] = integer("media-right-margin", MARGIN)
    c["media-top-margin"] = integer("media-top-margin", MARGIN)
    c["media-type"] = keyword("media-type", "stationery")
    c["media-source"] = keyword("media-source", "main")
    return c


class Job:
    _lock = threading.Lock()

    def __init__(self, jid, queue, name="Untitled", user="anonymous",
                 fmt="application/pdf"):
        self.id = jid
        self.queue = queue
        self.name = name
        self.user = user
        self.format = fmt
        self.state = PENDING
        self.reasons = ["none"]
        self.path = None
        self.size = 0
        self.created = int(time.time())
        self.processing_at = 0
        self.completed_at = 0
        self.impressions = 0
        self.detail = ""
        self.copies = 1
        self.pages = ""
        self.scale = "auto"
        self.mono = True
        self.duplex = False
        self.media = ""
        self.subset = ""          # "odd" / "even" for manual two-sided
        self.reverse = False
        self.closed = False        # Create-Job: document fully received

    @property
    def uri(self):
        return "%s/%d" % (self.queue.uri, self.id)

    def as_dict(self):
        return {
            "id": self.id, "name": self.name, "user": self.user,
            "state": STATE_NAMES.get(self.state, "unknown"),
            "bytes": self.size, "detail": self.detail,
            "created": self.created, "completed": self.completed_at,
        }

    def attrs(self, requested=None, up_time=0):
        g = Group(ipp.TAG_JOB)
        want = _wanted(requested)
        all_attrs = [
            uri("job-uri", self.uri),
            integer("job-id", self.id),
            uri("job-printer-uri", self.queue.uri),
            name_("job-name", self.name),
            name_("job-originating-user-name", self.user),
            enum("job-state", self.state),
            keyword("job-state-reasons", *(self.reasons or ["none"])),
            text("job-state-message", self.detail or STATE_NAMES.get(self.state, "")),
            integer("job-impressions", self.impressions or 1),
            integer("job-impressions-completed",
                    self.impressions if self.state == COMPLETED else 0),
            integer("job-k-octets", max(1, (self.size + 1023) // 1024)),
            integer("time-at-creation", self.created - self.queue.boot),
            (integer("time-at-processing", self.processing_at - self.queue.boot)
             if self.processing_at else novalue("time-at-processing")),
            (integer("time-at-completed", self.completed_at - self.queue.boot)
             if self.completed_at else novalue("time-at-completed")),
            integer("job-printer-up-time", up_time),
            mime("document-format", self.format),
            integer("copies", self.copies),
            keyword("print-scaling", self.scale),
            keyword("sides", "two-sided-long-edge" if self.duplex else "one-sided"),
            keyword("print-color-mode", "monochrome" if self.mono else "color"),
        ]
        for a in all_attrs:
            if want is None or a.name in want:
                g.add(a)
        return g


def _wanted(requested):
    """None means 'send everything'."""
    if not requested:
        return None
    req = set(requested)
    if "all" in req:
        return None
    return req


class Queue:
    """One printer, exposed over IPP."""

    def __init__(self, printer_name, backend, host="127.0.0.1", port=631,
                 dns_name=None, resource=None, location="", log=print,
                 make_and_model=None, brand=""):
        self.printer_name = printer_name
        self.backend = backend
        self.host = host
        self.port = port
        self.dns_name = dns_name or printer_name
        self.resource = resource or ("/ipp/print/" + slugify(printer_name))
        self.location = location
        self.log = log
        self.make_and_model = make_and_model or printer_name
        self.brand = brand
        self.boot = int(time.time())
        self.uuid = uuidlib.uuid5(
            uuidlib.NAMESPACE_DNS, "printbridge/%s" % printer_name)

        self._lock = threading.RLock()
        self._next_id = 1
        self.jobs = []                      # newest last
        self.state = 3                      # idle
        self.state_reasons = ["none"]
        self.accepting = True

        self._queue_event = threading.Event()
        self._stop = False
        self._worker = threading.Thread(target=self._run, daemon=True,
                                        name="print-%s" % self.resource)
        self._worker.start()

    # -- identity -----------------------------------------------------------
    @property
    def uri(self):
        return "ipp://%s:%d%s" % (self.host, self.port, self.resource)

    @property
    def http_uri(self):
        return "http://%s:%d%s" % (self.host, self.port, self.resource)

    def device_id(self):
        """1284 device ID. Driverless clients split this into make and model,
        so give them the real words rather than our own name."""
        words = self.make_and_model.split()
        mfg = self.brand or (words[0] if words else "Generic")
        mdl = " ".join(words[1:]) if len(words) > 1 else self.make_and_model
        return "MFG:%s;MDL:%s;CMD:PDF,JPEG,PNG;" % (mfg[:40], mdl[:60])

    def up_time(self):
        return max(1, int(time.time()) - self.boot)

    def set_host(self, host, port=None):
        self.host = host
        if port:
            self.port = port

    # -- jobs ---------------------------------------------------------------
    def new_job(self, name, user, fmt):
        with self._lock:
            job = Job(self._next_id, self, name, user, fmt)
            self._next_id += 1
            self.jobs.append(job)
            if len(self.jobs) > 200:
                self.jobs = self.jobs[-200:]
            return job

    def find_job(self, jid):
        with self._lock:
            for j in self.jobs:
                if j.id == jid:
                    return j
        return None

    def active_jobs(self):
        return [j for j in self.jobs if j.state in (PENDING, HELD, PROCESSING,
                                                    STOPPED)]

    def submit(self, job):
        job.closed = True
        if job.state == PENDING:
            self._queue_event.set()

    def cancel(self, job):
        with self._lock:
            if job.state in (COMPLETED, CANCELED, ABORTED):
                return False
            job.state = CANCELED
            job.reasons = ["job-canceled-by-user"]
            job.completed_at = int(time.time())
            self._cleanup(job)
            return True

    def _cleanup(self, job):
        if job.path and os.path.exists(job.path):
            try:
                os.unlink(job.path)
            except OSError:
                pass
        job.path = None

    def shutdown(self):
        self._stop = True
        self._queue_event.set()

    # -- the worker ---------------------------------------------------------
    def _run(self):
        while not self._stop:
            self._queue_event.wait(1.0)
            self._queue_event.clear()
            while not self._stop:
                job = None
                with self._lock:
                    for j in self.jobs:
                        if j.state == PENDING and j.closed and j.path:
                            job = j
                            break
                if job is None:
                    break
                self._print(job)

    def _print(self, job):
        job.state = PROCESSING
        job.reasons = ["job-printing"]
        job.processing_at = int(time.time())
        self.state = 4                       # processing
        self.log("  printing job %d (%s, %.0f KB) on %s"
                 % (job.id, job.name, job.size / 1024.0, self.printer_name))
        try:
            res = self.backend.print_file(
                job.path, self.printer_name, copies=job.copies, pages=job.pages,
                scale=job.scale, mono=job.mono, duplex=job.duplex,
                paper=job.media, label=job.name, subset=job.subset,
                reverse=job.reverse,
            )
            ok, detail = res.ok, res.detail
        except Exception as e:                # never let the worker die
            ok, detail = False, "%s: %s" % (type(e).__name__, e)

        job.completed_at = int(time.time())
        job.detail = detail
        if ok:
            job.state = COMPLETED
            job.reasons = ["job-completed-successfully"]
            job.impressions = job.impressions or 1
            self.log("  job %d done  (%s)" % (job.id, detail or "ok"))
        else:
            job.state = ABORTED
            job.reasons = ["job-canceled-at-device"]
            self.log("  job %d FAILED  %s" % (job.id, detail))
        self._cleanup(job)
        self.state = 3
        self.state_reasons = ["none"]

    # -- printer attributes --------------------------------------------------
    def printer_attrs(self, requested=None):
        want = _wanted(requested)
        req = set(requested or [])
        group = Group(ipp.TAG_PRINTER)

        media_default = "iso_a4_210x297mm"
        media_list = list(MEDIA.keys())

        attrs = [
            # --- identity
            uri("printer-uri-supported", self.uri),
            keyword("uri-security-supported", "none"),
            keyword("uri-authentication-supported", "requesting-user-name"),
            name_("printer-name", self.dns_name),
            name_("printer-dns-sd-name", self.dns_name),
            text("printer-info", self.printer_name),
            text("printer-make-and-model", self.make_and_model),
            text("printer-location", self.location),
            uri("printer-more-info", "http://%s:%d/" % (self.host, self.port)),
            uri("printer-uuid", "urn:uuid:%s" % self.uuid),
            text("printer-device-id", self.device_id()),
            text("printer-organization", ""),
            text("printer-organizational-unit", ""),
            unknown_geo(),

            # --- state
            enum("printer-state", self.state),
            keyword("printer-state-reasons", *self.state_reasons),
            text("printer-state-message", "ready"),
            boolean("printer-is-accepting-jobs", self.accepting),
            integer("queued-job-count", len(self.active_jobs())),
            integer("printer-up-time", self.up_time()),
            integer("printer-config-change-time", 1),
            integer("printer-state-change-time", 1),

            # --- protocol
            keyword("ipp-versions-supported", "1.0", "1.1", "2.0"),
            # deliberately not claiming "ipp-everywhere": that promises
            # PWG-raster input, and this bridge only takes PDF and images.
            keyword("ipp-features-supported", "none"),
            enum("operations-supported", *OPERATIONS),
            charset("charset-configured", "utf-8"),
            charset("charset-supported", "utf-8"),
            language("natural-language-configured", "en"),
            language("generated-natural-language-supported", "en"),
            mime("document-format-default", "application/pdf"),
            mime("document-format-supported", *FORMATS),
            keyword("urf-supported", *URF_SUPPORTED),
            resolution("pwg-raster-document-resolution-supported",
                       ipp.Resolution(300, 300, 3), ipp.Resolution(600, 600, 3)),
            keyword("pwg-raster-document-type-supported", "sgray_8", "srgb_8"),
            keyword("pwg-raster-document-sheet-back", "normal"),
            keyword("compression-supported", "none"),
            keyword("pdl-override-supported", "attempted"),
            boolean("multiple-document-jobs-supported", False),
            integer("multiple-operation-time-out", 150),
            keyword("multiple-operation-time-out-action", "process-job"),
            keyword("which-jobs-supported", "completed", "not-completed", "all"),
            keyword("job-creation-attributes-supported",
                    "copies", "media", "media-col", "orientation-requested",
                    "print-color-mode", "print-quality", "print-scaling",
                    "printer-resolution", "sides", "job-name", "page-ranges",
                    "ipp-attribute-fidelity", "document-format",
                    "requesting-user-name"),
            keyword("identify-actions-supported", "display"),
            keyword("identify-actions-default", "display"),
            boolean("color-supported", False),
            keyword("printer-get-attributes-supported", "document-format"),
            boolean("page-ranges-supported", True),
            boolean("job-ids-supported", True),
            rangeof("job-k-octets-supported", ipp.IntRange(0, 262144)),

            # --- job template
            integer("copies-default", 1),
            rangeof("copies-supported", ipp.IntRange(1, 99)),
            enum("finishings-default", 3),
            enum("finishings-supported", 3),
            keyword("media-default", media_default),
            keyword("media-supported", *media_list),
            keyword("media-ready", media_default),
            keyword("media-source-supported", "main", "auto"),
            keyword("media-type-supported", "stationery", "auto"),
            collection("media-col-default", _media_col(media_default)),
            Attr("media-size-supported", ipp.TAG_BEG_COLLECTION,
                 [_media_size(m) for m in media_list]),
            keyword("media-col-supported",
                    "media-size", "media-top-margin", "media-bottom-margin",
                    "media-left-margin", "media-right-margin", "media-type",
                    "media-source"),
            integer("pages-per-minute", 18),
            integer("number-up-default", 1),
            integer("number-up-supported", 1, 2, 4),
            enum("orientation-requested-default", 3),
            enum("orientation-requested-supported", 3, 4, 5, 6),
            keyword("output-bin-default", "face-down"),
            keyword("output-bin-supported", "face-down"),
            keyword("print-color-mode-default", "monochrome"),
            keyword("print-color-mode-supported", "monochrome", "auto"),
            enum("print-quality-default", 4),
            enum("print-quality-supported", 3, 4, 5),
            keyword("print-scaling-default", "auto"),
            keyword("print-scaling-supported", "auto", "auto-fit", "fill",
                    "fit", "none"),
            resolution("printer-resolution-default", ipp.Resolution(600, 600, 3)),
            resolution("printer-resolution-supported", ipp.Resolution(600, 600, 3)),
            keyword("sides-default", "one-sided"),
            keyword("sides-supported", "one-sided"),
            keyword("job-sheets-default", "none"),
            keyword("job-sheets-supported", "none"),
            keyword("print-content-optimize-default", "auto"),
            keyword("print-content-optimize-supported", "auto", "text",
                    "graphic", "photo", "text-and-graphic"),

            # --- supplies, so phones show a toner bar rather than nothing
            text("printer-supply-info-uri", "http://%s:%d/" % (self.host, self.port)),
            uri("printer-icons",
                "http://%s:%d/icons/printer-48.png" % (self.host, self.port),
                "http://%s:%d/icons/printer-128.png" % (self.host, self.port),
                "http://%s:%d/icons/printer-512.png" % (self.host, self.port)),
        ]

        for a in attrs:
            if want is None or a.name in want:
                group.add(a)

        # expensive, and only ever sent when asked for by name
        if "media-col-database" in req:
            group.add(Attr("media-col-database", ipp.TAG_BEG_COLLECTION,
                           [_media_col(m) for m in media_list]))
        if "media-col-ready" in req or want is None:
            group.add(collection("media-col-ready", _media_col(media_default)))

        return group


def unknown_geo():
    return Attr("printer-geo-location", ipp.TAG_UNKNOWN, b"")
