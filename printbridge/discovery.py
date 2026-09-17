"""
Bonjour/mDNS advertisement - the part that makes the printer simply appear
in the iPhone's Print sheet and in Android's Mopria list.

iOS looks for _ipp._tcp with the _universal AirPrint subtype and a TXT record
that names the formats the printer accepts. Android/Mopria looks for plain
_ipp._tcp. Advertising both from one registration covers everything.
"""

from __future__ import annotations

import socket

try:
    from zeroconf import IPVersion, ServiceInfo, Zeroconf
    HAVE_ZEROCONF = True
except ImportError:                                  # pragma: no cover
    HAVE_ZEROCONF = False
    Zeroconf = ServiceInfo = IPVersion = None

IPP_TYPE = "_ipp._tcp.local."
UNIVERSAL_SUBTYPE = "_universal._sub._ipp._tcp.local."


def local_ip(probe="8.8.8.8"):
    """The address this machine uses to reach the LAN. No traffic is sent."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((probe, 80))
        return s.getsockname()[0]
    except OSError:
        try:
            return socket.gethostbyname(socket.gethostname())
        except OSError:
            return "127.0.0.1"
    finally:
        s.close()


SCAN_TYPE = "_uscan._tcp.local."


def scan_txt_records(scanner, host, port):
    """What a phone reads before it decides to show the scanner."""
    sources = "platen,adf" if scanner.has_feeder else "platen"
    return {
        b"txtvers": b"1",
        b"vers": b"2.6",
        b"ty": _clean(scanner.name, 63).encode("utf-8"),
        b"rs": b"eSCL",
        b"pdl": b"image/jpeg,application/pdf",
        b"cs": b"color,grayscale,binary",
        b"is": sources.encode("ascii"),
        b"duplex": b"F",
        b"note": b"",
        b"adminurl": ("http://%s:%d/" % (host, port)).encode("utf-8"),
        b"representation": b"/icons/printer-192.png",
    }


def _clean(s, limit=63):
    return "".join(c for c in str(s) if 32 <= ord(c) < 127).strip()[:limit]


def txt_records(queue, formats=None, pin=False):
    """The keys iOS, Android and macOS read before they will even try.

    Values here are deliberately close to what CUPS advertises for a shared
    queue, because that is the combination iPhones are known to accept.
    """
    from .model import FORMATS, URF_SUPPORTED
    if formats is None:
        formats = [f for f in FORMATS if f != "application/octet-stream"]
    rp = queue.resource.lstrip("/")
    return {
        "txtvers": "1",
        "qtotal": "1",
        "rp": rp,
        "ty": _clean(queue.make_and_model),
        "product": "(PrintBridge)",
        "note": _clean(queue.location or "PrintBridge"),
        "adminurl": "http://%s:%d/" % (queue.host, queue.port),
        "priority": "0",
        "pdl": ",".join(formats),
        # An iPhone will not offer a printer whose URF key says "none" - it
        # reads that as "not an AirPrint device" and hides it. These are the
        # Apple Raster capabilities the bridge really does decode.
        "URF": ",".join(URF_SUPPORTED),
        "mopria-certified": "1.3",
        "air": "username,password" if pin else "none",
        "kind": "document",
        "PaperMax": "legal-A4",
        "Color": "F",
        "Duplex": "F",
        "Copies": "T",
        "Collate": "F",
        "Bind": "F",
        "Sort": "F",
        "Staple": "F",
        "Punch": "F",
        "Scan": "F",
        "Fax": "F",
        "Transparent": "T",
        "Binary": "T",
        "TBCP": "F",
        # no TLS key at all: an empty one invites a client to try HTTPS here
        "UUID": str(queue.uuid),
        "printer-state": "3",
        # black and white, multiple copies. Nothing more is claimed.
        "printer-type": "0x0044",
    }


class Advertiser:
    def __init__(self, log=print):
        self.log = log
        self.zc = None
        self.zc_sub = None
        self.infos = []
        self.sub_infos = []
        self.names = []
        self.scanner_name = ""
        self.local_name = ""

    def start(self, queues, ip, port, hostname=None, pin=False, scanner=None):
        if not HAVE_ZEROCONF:
            self.log("  ! zeroconf is not installed - phones will not see the "
                     "printer automatically.")
            self.log("    fix it with:  pip install zeroconf")
            return False

        try:
            self.zc = Zeroconf(ip_version=IPVersion.V4Only, interfaces=[ip])
        except Exception as e:
            self.log("  ! could not start mDNS on %s: %s" % (ip, e))
            self.log("    the web page still works; native discovery will not.")
            self.zc = None
            return False

        # python-zeroconf keys its registry by instance name, so the AirPrint
        # subtype - same instance, different browse type - needs a second
        # responder alongside the first. Both answer for the same records.
        try:
            self.zc_sub = Zeroconf(ip_version=IPVersion.V4Only, interfaces=[ip])
        except Exception:
            self.zc_sub = None

        host = _clean(hostname or socket.gethostname().split(".")[0]) or "pc"
        host = "".join(c if (c.isalnum() or c == "-") else "-" for c in host)
        # Windows runs its own mDNS responder and already answers for
        # <pc-name>.local. Claiming the same name can leave a phone resolving
        # to whichever adapter Windows felt like naming - a VPN, say. Our own
        # name avoids the argument entirely.
        label = ("printbridge-%s" % host).strip("-")[:60]
        server = "%s.local." % label
        self.local_name = "%s.local" % label
        addr = socket.inet_aton(ip)

        ok = 0
        for q in queues:
            instance = _clean("%s @ %s" % (q.dns_name, host), 60)
            props = txt_records(q, pin=pin)
            info = ServiceInfo(
                IPP_TYPE, "%s.%s" % (instance, IPP_TYPE),
                addresses=[addr], port=port, properties=props, server=server,
            )
            try:
                self.zc.register_service(info, allow_name_change=True)
            except Exception as e:
                self.log("  ! could not advertise %s: %s" % (q.printer_name, e))
                continue
            self.infos.append(info)

            # The AirPrint subtype: iOS browses _universal._sub._ipp._tcp and
            # ignores printers that only answer on the bare type. Same instance
            # name, so this is our own record - hence cooperating_responders.
            sub = ServiceInfo(
                UNIVERSAL_SUBTYPE, info.name,
                addresses=[addr], port=port, properties=props, server=server,
            )
            if self.zc_sub is not None:
                try:
                    self.zc_sub.register_service(sub, cooperating_responders=True,
                                                 strict=False)
                    self.sub_infos.append(sub)
                except Exception as e:
                    self.log("  ! AirPrint subtype for %s failed (%s: %s); "
                             "iPhones may not see it"
                             % (q.printer_name, type(e).__name__, e))

            self.names.append(info.name.split(".")[0])
            ok += 1

        # the scanner, if this PC has one. Same responder, same port - to a
        # phone it is simply another service on the same machine.
        if scanner is not None:
            try:
                instance = _clean("%s @ %s" % (scanner.name, host), 60)
                sinfo = ServiceInfo(
                    SCAN_TYPE, "%s.%s" % (instance, SCAN_TYPE),
                    addresses=[addr], port=port,
                    properties=scan_txt_records(scanner, ip, port),
                    server=server,
                )
                self.zc.register_service(sinfo, allow_name_change=True)
                self.infos.append(sinfo)
                self.scanner_name = sinfo.name.split(".")[0]
            except Exception as e:
                self.log("  ! could not advertise the scanner: %s" % e)

        return ok > 0

    def stop(self):
        for zc, infos in ((self.zc, self.infos), (self.zc_sub, self.sub_infos)):
            if not zc:
                continue
            for info in infos:
                try:
                    zc.unregister_service(info)
                except Exception:
                    pass
            try:
                zc.close()
            except Exception:
                pass
        self.zc = self.zc_sub = None
