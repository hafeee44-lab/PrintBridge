"""
eSCL - the scanning cousin of AirPrint.

iPhones and iPads speak it out of the box (Files, then Scan Documents), and so
does Mopria Scan on Android. It is plain HTTP with a little XML, which means
the scanner can live on the same port and the same mDNS responder as the
printer; nothing new has to be opened or installed.

Only the part clients actually use is implemented: say what the scanner can
do, say whether it is busy, take a job, hand back the page.
"""

from __future__ import annotations

import threading
import time
import uuid as uuidlib

from . import scan as scanmod

NS = ('xmlns:scan="http://schemas.hp.com/imaging/escl/2011/05/03" '
      'xmlns:pwg="http://www.pwg.org/schemas/2010/12/sm"')

# eSCL talks in 1/300th of an inch, whatever the scan resolution is
UNITS = 300

COLOUR_MODES = {
    "color": "RGB24",
    "gray": "Grayscale8",
    "bw": "BlackAndWhite1",
}
FROM_ESCL = {
    "RGB24": "color", "RGB48": "color",
    "Grayscale8": "gray", "Grayscale16": "gray",
    "BlackAndWhite1": "bw",
}


def _esc(text):
    return (str(text).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def capabilities_xml(scanner, version="2.6"):
    """What the scanner can do, in the shape clients expect."""
    width = int(round(scanner.max_width_in * UNITS))
    height = int(round(scanner.max_height_in * UNITS))
    resolutions = "".join(
        "<scan:DiscreteResolution>"
        "<scan:XResolution>%d</scan:XResolution>"
        "<scan:YResolution>%d</scan:YResolution>"
        "</scan:DiscreteResolution>" % (r, r)
        for r in scanner.resolutions)
    formats = ("<pwg:DocumentFormat>image/jpeg</pwg:DocumentFormat>"
               "<pwg:DocumentFormat>application/pdf</pwg:DocumentFormat>"
               "<scan:DocumentFormatExt>image/jpeg</scan:DocumentFormatExt>"
               "<scan:DocumentFormatExt>application/pdf</scan:DocumentFormatExt>")
    colours = "".join("<scan:ColorMode>%s</scan:ColorMode>" % v
                      for v in ("RGB24", "Grayscale8", "BlackAndWhite1"))

    profile = (
        "<scan:SettingProfile>"
        "<scan:ColorModes>%s</scan:ColorModes>"
        "<scan:DocumentFormats>%s</scan:DocumentFormats>"
        "<scan:SupportedResolutions><scan:DiscreteResolutions>%s"
        "</scan:DiscreteResolutions></scan:SupportedResolutions>"
        "</scan:SettingProfile>" % (colours, formats, resolutions))

    def source(tag):
        return (
            "<scan:%s>"
            "<scan:MinWidth>16</scan:MinWidth>"
            "<scan:MaxWidth>%d</scan:MaxWidth>"
            "<scan:MinHeight>16</scan:MinHeight>"
            "<scan:MaxHeight>%d</scan:MaxHeight>"
            "<scan:MaxScanRegions>1</scan:MaxScanRegions>"
            "<scan:SettingProfiles>%s</scan:SettingProfiles>"
            "<scan:MaxOpticalXResolution>%d</scan:MaxOpticalXResolution>"
            "<scan:MaxOpticalYResolution>%d</scan:MaxOpticalYResolution>"
            "</scan:%s>" % (tag, width, height, profile,
                            max(scanner.resolutions), max(scanner.resolutions), tag))

    feeder = ("<scan:Adf><scan:AdfSimplexInputCaps>%s</scan:AdfSimplexInputCaps>"
              "</scan:Adf>" % source("AdfSimplexInputCaps")[len("<scan:AdfSimplexInputCaps>"):
                                                            -len("</scan:AdfSimplexInputCaps>")]
              ) if scanner.has_feeder else ""

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<scan:ScannerCapabilities %s>'
        '<pwg:Version>%s</pwg:Version>'
        '<pwg:MakeAndModel>%s</pwg:MakeAndModel>'
        '<pwg:SerialNumber>printbridge</pwg:SerialNumber>'
        '<scan:UUID>%s</scan:UUID>'
        '<scan:Platen><scan:PlatenInputCaps>%s</scan:PlatenInputCaps></scan:Platen>'
        '%s'
        '</scan:ScannerCapabilities>'
        % (NS, version, _esc(scanner.name),
           uuidlib.uuid5(uuidlib.NAMESPACE_DNS, "printbridge-scan/" + scanner.device_id),
           source("PlatenInputCaps")[len("<scan:PlatenInputCaps>"):
                                     -len("</scan:PlatenInputCaps>")],
           feeder))


def status_xml(state="Idle", jobs=()):
    entries = "".join(
        "<scan:JobInfo>"
        "<pwg:JobUri>/eSCL/ScanJobs/%s</pwg:JobUri>"
        "<pwg:JobUuid>%s</pwg:JobUuid>"
        "<scan:Age>%d</scan:Age>"
        "<pwg:ImagesCompleted>%d</pwg:ImagesCompleted>"
        "<pwg:JobState>%s</pwg:JobState>"
        "<pwg:JobStateReasons><pwg:JobStateReason>%s</pwg:JobStateReason>"
        "</pwg:JobStateReasons>"
        "</scan:JobInfo>" % (j.job_id, j.job_id, int(time.time() - j.created),
                             j.delivered, j.state, j.reason)
        for j in jobs)
    return ('<?xml version="1.0" encoding="UTF-8"?>\n'
            '<scan:ScannerStatus %s>'
            '<pwg:Version>2.6</pwg:Version>'
            '<pwg:State>%s</pwg:State>'
            '<scan:Jobs>%s</scan:Jobs>'
            '</scan:ScannerStatus>' % (NS, state, entries))


class ScanJob:
    def __init__(self, dpi=300, mode="color", fmt="image/jpeg"):
        self.job_id = uuidlib.uuid4().hex[:16]
        self.dpi = dpi
        self.mode = mode
        self.format = fmt
        self.created = time.time()
        self.state = "Pending"
        self.reason = "JobQueued"
        self.delivered = 0
        self.lock = threading.Lock()


def parse_scan_settings(body):
    """Pull the few settings we honour out of a ScanSettings document."""
    text = (body or b"").decode("utf-8", "replace")

    def tag(name, default=None):
        start = text.find("<" + name)
        if start < 0:
            start = text.find(":" + name)
            if start < 0:
                return default
            start = text.rfind("<", 0, start)
        close = text.find(">", start)
        end = text.find("<", close + 1)
        if close < 0 or end < 0:
            return default
        return text[close + 1:end].strip() or default

    try:
        dpi = int(tag("XResolution", "300"))
    except (TypeError, ValueError):
        dpi = 300
    colour = tag("ColorMode", "RGB24") or "RGB24"
    fmt = tag("DocumentFormatExt") or tag("DocumentFormat") or "image/jpeg"
    return {
        "dpi": max(50, min(1200, dpi)),
        "mode": FROM_ESCL.get(colour, "color"),
        "format": "application/pdf" if "pdf" in fmt.lower() else "image/jpeg",
    }
