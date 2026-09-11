"""
Minimal but conformant IPP/2.0 message layer.

Everything here is protocol plumbing: turning the binary IPP encoding into
Python objects and back. It knows nothing about printers, Windows, or jobs.

Encoding reference: RFC 8010 (IPP/1.1 encoding and transport).
"""

from __future__ import annotations

import struct
from collections import OrderedDict

# ---------------------------------------------------------------------------
# tags
# ---------------------------------------------------------------------------

# delimiters
TAG_OPERATION = 0x01
TAG_JOB = 0x02
TAG_END = 0x03
TAG_PRINTER = 0x04
TAG_UNSUPPORTED_GROUP = 0x05

DELIMITERS = (TAG_OPERATION, TAG_JOB, TAG_END, TAG_PRINTER, TAG_UNSUPPORTED_GROUP)

# out-of-band values
TAG_UNSUPPORTED_VALUE = 0x10
TAG_DEFAULT = 0x11
TAG_UNKNOWN = 0x12
TAG_NO_VALUE = 0x13

OUT_OF_BAND = (0x10, 0x11, 0x12, 0x13, 0x15, 0x16, 0x17)

# value tags
TAG_INTEGER = 0x21
TAG_BOOLEAN = 0x22
TAG_ENUM = 0x23
TAG_OCTET_STRING = 0x30
TAG_DATETIME = 0x31
TAG_RESOLUTION = 0x32
TAG_RANGE = 0x33
TAG_BEG_COLLECTION = 0x34
TAG_TEXT_LANG = 0x35
TAG_NAME_LANG = 0x36
TAG_END_COLLECTION = 0x37
TAG_TEXT = 0x41
TAG_NAME = 0x42
TAG_KEYWORD = 0x44
TAG_URI = 0x45
TAG_URI_SCHEME = 0x46
TAG_CHARSET = 0x47
TAG_LANGUAGE = 0x48
TAG_MIME = 0x49
TAG_MEMBER_NAME = 0x4A

STRING_TAGS = (
    TAG_OCTET_STRING, TAG_TEXT, TAG_NAME, TAG_KEYWORD, TAG_URI,
    TAG_URI_SCHEME, TAG_CHARSET, TAG_LANGUAGE, TAG_MIME, TAG_MEMBER_NAME,
)

# ---------------------------------------------------------------------------
# operations
# ---------------------------------------------------------------------------

OP_PRINT_JOB = 0x0002
OP_PRINT_URI = 0x0003
OP_VALIDATE_JOB = 0x0004
OP_CREATE_JOB = 0x0005
OP_SEND_DOCUMENT = 0x0006
OP_SEND_URI = 0x0007
OP_CANCEL_JOB = 0x0008
OP_GET_JOB_ATTRIBUTES = 0x0009
OP_GET_JOBS = 0x000A
OP_GET_PRINTER_ATTRIBUTES = 0x000B
OP_HOLD_JOB = 0x000C
OP_RELEASE_JOB = 0x000D
OP_PAUSE_PRINTER = 0x0010
OP_RESUME_PRINTER = 0x0011
OP_PURGE_JOBS = 0x0012
OP_CANCEL_MY_JOBS = 0x0039
OP_CLOSE_JOB = 0x003B
OP_IDENTIFY_PRINTER = 0x003C
OP_CUPS_GET_DEFAULT = 0x4001
OP_CUPS_GET_PRINTERS = 0x4002

OP_NAMES = {
    OP_PRINT_JOB: "Print-Job",
    OP_PRINT_URI: "Print-URI",
    OP_VALIDATE_JOB: "Validate-Job",
    OP_CREATE_JOB: "Create-Job",
    OP_SEND_DOCUMENT: "Send-Document",
    OP_SEND_URI: "Send-URI",
    OP_CANCEL_JOB: "Cancel-Job",
    OP_GET_JOB_ATTRIBUTES: "Get-Job-Attributes",
    OP_GET_JOBS: "Get-Jobs",
    OP_GET_PRINTER_ATTRIBUTES: "Get-Printer-Attributes",
    OP_HOLD_JOB: "Hold-Job",
    OP_RELEASE_JOB: "Release-Job",
    OP_PAUSE_PRINTER: "Pause-Printer",
    OP_RESUME_PRINTER: "Resume-Printer",
    OP_PURGE_JOBS: "Purge-Jobs",
    OP_CANCEL_MY_JOBS: "Cancel-My-Jobs",
    OP_CLOSE_JOB: "Close-Job",
    OP_IDENTIFY_PRINTER: "Identify-Printer",
}

# ---------------------------------------------------------------------------
# status codes
# ---------------------------------------------------------------------------

OK = 0x0000
OK_IGNORED = 0x0001
OK_CONFLICTING = 0x0002
ERR_BAD_REQUEST = 0x0400
ERR_FORBIDDEN = 0x0401
ERR_NOT_AUTHENTICATED = 0x0402
ERR_NOT_AUTHORIZED = 0x0403
ERR_NOT_POSSIBLE = 0x0404
ERR_TIMEOUT = 0x0405
ERR_NOT_FOUND = 0x0406
ERR_GONE = 0x0407
ERR_TOO_LARGE = 0x0408
ERR_VALUE_TOO_LONG = 0x0409
ERR_FORMAT_NOT_SUPPORTED = 0x040A
ERR_ATTRIBUTES_NOT_SUPPORTED = 0x040B
ERR_URI_SCHEME_NOT_SUPPORTED = 0x040C
ERR_CHARSET_NOT_SUPPORTED = 0x040D
ERR_CONFLICTING = 0x040E
ERR_COMPRESSION_NOT_SUPPORTED = 0x040F
ERR_DOCUMENT_FORMAT_ERROR = 0x0411
ERR_INTERNAL = 0x0500
ERR_OPERATION_NOT_SUPPORTED = 0x0501
ERR_SERVICE_UNAVAILABLE = 0x0502
ERR_VERSION_NOT_SUPPORTED = 0x0503
ERR_DEVICE_ERROR = 0x0504
ERR_TEMPORARY_ERROR = 0x0505
ERR_NOT_ACCEPTING_JOBS = 0x0506
ERR_BUSY = 0x0507
ERR_JOB_CANCELED = 0x0508

# ---------------------------------------------------------------------------
# value helper types
# ---------------------------------------------------------------------------


class Resolution:
    __slots__ = ("x", "y", "units")

    def __init__(self, x, y, units=3):   # 3 = dots per inch, 4 = per cm
        self.x, self.y, self.units = x, y, units

    def __eq__(self, o):
        return (isinstance(o, Resolution) and (self.x, self.y, self.units)
                == (o.x, o.y, o.units))

    def __repr__(self):
        return "%dx%ddpi" % (self.x, self.y)


class IntRange:
    __slots__ = ("lower", "upper")

    def __init__(self, lower, upper):
        self.lower, self.upper = lower, upper

    def __repr__(self):
        return "%d-%d" % (self.lower, self.upper)


class Collection(OrderedDict):
    """An IPP collection value: member name -> Attr."""


class Attr:
    """One attribute: a name, a value tag, and one or more values."""

    __slots__ = ("name", "tag", "values")

    def __init__(self, name, tag, *values):
        self.name = name
        self.tag = tag
        if len(values) == 1 and isinstance(values[0], (list, tuple)):
            values = list(values[0])
        self.values = list(values)

    @property
    def value(self):
        return self.values[0] if self.values else None

    def __repr__(self):
        return "Attr(%r, 0x%02x, %r)" % (self.name, self.tag, self.values)


# short constructors, used heavily when declaring printer attributes
def integer(name, *v):  return Attr(name, TAG_INTEGER, *v)
def boolean(name, *v):  return Attr(name, TAG_BOOLEAN, *v)
def enum(name, *v):     return Attr(name, TAG_ENUM, *v)
def keyword(name, *v):  return Attr(name, TAG_KEYWORD, *v)
def text(name, *v):     return Attr(name, TAG_TEXT, *v)
def name_(name, *v):    return Attr(name, TAG_NAME, *v)
def uri(name, *v):      return Attr(name, TAG_URI, *v)
def charset(name, *v):  return Attr(name, TAG_CHARSET, *v)
def language(name, *v): return Attr(name, TAG_LANGUAGE, *v)
def mime(name, *v):     return Attr(name, TAG_MIME, *v)
def resolution(name, *v): return Attr(name, TAG_RESOLUTION, *v)
def rangeof(name, *v):  return Attr(name, TAG_RANGE, *v)
def collection(name, *v): return Attr(name, TAG_BEG_COLLECTION, *v)
def novalue(name):      return Attr(name, TAG_NO_VALUE, b"")
def unknown(name):      return Attr(name, TAG_UNKNOWN, b"")


class Group:
    """A delimited attribute group."""

    __slots__ = ("tag", "attrs")

    def __init__(self, tag, attrs=None):
        self.tag = tag
        self.attrs = list(attrs or [])

    def add(self, attr):
        self.attrs.append(attr)
        return self

    def get(self, name, default=None):
        for a in self.attrs:
            if a.name == name:
                return a
        return default

    def value(self, name, default=None):
        a = self.get(name)
        return a.value if a is not None and a.values else default

    def values(self, name):
        a = self.get(name)
        return list(a.values) if a is not None else []

    def __iter__(self):
        return iter(self.attrs)


class Message:
    """A whole IPP request or response, minus any trailing document data."""

    def __init__(self, version=(2, 0), code=0, request_id=1, groups=None):
        self.version = version
        self.code = code            # operation-id on requests, status on responses
        self.request_id = request_id
        self.groups = list(groups or [])

    # -- convenience ---------------------------------------------------------
    @property
    def operation(self):
        return self.code

    def group(self, tag):
        for g in self.groups:
            if g.tag == tag:
                return g
        return None

    @property
    def op_attrs(self):
        return self.group(TAG_OPERATION) or Group(TAG_OPERATION)

    @property
    def job_attrs(self):
        return self.group(TAG_JOB) or Group(TAG_JOB)

    def add_group(self, group):
        self.groups.append(group)
        return group


class IppError(Exception):
    def __init__(self, status, message=""):
        super().__init__(message or ("IPP status 0x%04x" % status))
        self.status = status
        self.message = message


# ---------------------------------------------------------------------------
# decoding
# ---------------------------------------------------------------------------


class _Reader:
    """Wraps any object with .read(n) and guarantees exact-length reads."""

    def __init__(self, stream):
        self.stream = stream
        self.consumed = 0

    def exact(self, n):
        buf = b""
        while len(buf) < n:
            chunk = self.stream.read(n - len(buf))
            if not chunk:
                raise IppError(ERR_BAD_REQUEST, "truncated IPP message")
            buf += chunk
        self.consumed += n
        return buf

    def u8(self):
        return self.exact(1)[0]

    def u16(self):
        return struct.unpack(">H", self.exact(2))[0]

    def i32(self):
        return struct.unpack(">i", self.exact(4))[0]


def _decode_value(tag, raw):
    if tag in OUT_OF_BAND:
        return None
    if tag == TAG_INTEGER or tag == TAG_ENUM:
        if len(raw) != 4:
            raise IppError(ERR_BAD_REQUEST, "bad integer length")
        return struct.unpack(">i", raw)[0]
    if tag == TAG_BOOLEAN:
        return bool(raw and raw[0])
    if tag == TAG_RESOLUTION:
        if len(raw) != 9:
            raise IppError(ERR_BAD_REQUEST, "bad resolution length")
        x, y, u = struct.unpack(">iib", raw)
        return Resolution(x, y, u)
    if tag == TAG_RANGE:
        if len(raw) != 8:
            raise IppError(ERR_BAD_REQUEST, "bad range length")
        lo, hi = struct.unpack(">ii", raw)
        return IntRange(lo, hi)
    if tag in (TAG_TEXT_LANG, TAG_NAME_LANG):
        # [lang-len][lang][text-len][text] - we keep the text only
        if len(raw) < 4:
            return ""
        ll = struct.unpack(">H", raw[0:2])[0]
        rest = raw[2 + ll:]
        tl = struct.unpack(">H", rest[0:2])[0]
        return rest[2:2 + tl].decode("utf-8", "replace")
    if tag in STRING_TAGS:
        return raw.decode("utf-8", "replace")
    return raw


def decode(stream):
    """Read one IPP message from a byte stream.

    Stops immediately after the end-of-attributes tag, leaving any document
    data still unread in the stream - which is exactly what Print-Job needs.
    """
    r = _Reader(stream)
    major = r.u8()
    minor = r.u8()
    code = r.u16()
    request_id = r.i32()

    msg = Message((major, minor), code, request_id, [])
    group = None
    # stack of (collection, pending member name) for nested collections
    coll_stack = []
    last_attr = None

    while True:
        tag = r.u8()

        if tag == TAG_END:
            break

        if tag in DELIMITERS:
            group = Group(tag)
            msg.groups.append(group)
            last_attr = None
            continue

        name_len = r.u16()
        name = r.exact(name_len).decode("utf-8", "replace") if name_len else ""
        val_len = r.u16()
        raw = r.exact(val_len) if val_len else b""

        # --- collections ----------------------------------------------------
        if tag == TAG_BEG_COLLECTION:
            new = Collection()
            if coll_stack:
                parent, member = coll_stack[-1]
                if member is None:
                    raise IppError(ERR_BAD_REQUEST, "collection without member name")
                parent.setdefault(member, []).append(new)
                coll_stack[-1] = (parent, None)
            else:
                if group is None:
                    raise IppError(ERR_BAD_REQUEST, "attribute outside a group")
                if (name_len == 0 and last_attr is not None
                        and last_attr.tag == TAG_BEG_COLLECTION):
                    last_attr.values.append(new)      # another set member
                else:
                    last_attr = Attr(name, TAG_BEG_COLLECTION, new)
                    group.attrs.append(last_attr)
            coll_stack.append((new, None))
            continue

        if tag == TAG_END_COLLECTION:
            if coll_stack:
                coll_stack.pop()
            continue

        if tag == TAG_MEMBER_NAME:
            if not coll_stack:
                raise IppError(ERR_BAD_REQUEST, "member name outside a collection")
            parent, _ = coll_stack[-1]
            coll_stack[-1] = (parent, raw.decode("utf-8", "replace"))
            continue

        value = _decode_value(tag, raw)

        if coll_stack:
            parent, member = coll_stack[-1]
            if member is None:
                # additional value for the previous member
                if parent:
                    lastkey = next(reversed(parent))
                    parent[lastkey].append(value)
                continue
            parent.setdefault(member, []).append(value)
            coll_stack[-1] = (parent, None)
            continue

        if group is None:
            raise IppError(ERR_BAD_REQUEST, "attribute outside a group")

        if name_len == 0 and last_attr is not None:
            last_attr.values.append(value)      # additional value of a set
        else:
            last_attr = Attr(name, tag, value)
            group.attrs.append(last_attr)

    return msg


# ---------------------------------------------------------------------------
# encoding
# ---------------------------------------------------------------------------


def _encode_value(tag, value):
    if tag in OUT_OF_BAND:
        return b""
    if tag in (TAG_INTEGER, TAG_ENUM):
        return struct.pack(">i", int(value))
    if tag == TAG_BOOLEAN:
        return b"\x01" if value else b"\x00"
    if tag == TAG_RESOLUTION:
        return struct.pack(">iib", value.x, value.y, value.units)
    if tag == TAG_RANGE:
        return struct.pack(">ii", value.lower, value.upper)
    if tag in (TAG_TEXT_LANG, TAG_NAME_LANG):
        lang = b"en"
        body = value.encode("utf-8") if isinstance(value, str) else value
        return (struct.pack(">H", len(lang)) + lang
                + struct.pack(">H", len(body)) + body)
    if isinstance(value, bytes):
        return value
    return str(value).encode("utf-8")


def _encode_attr(attr, out):
    if attr.tag == TAG_BEG_COLLECTION:
        for i, coll in enumerate(attr.values):
            nm = attr.name.encode("utf-8") if i == 0 else b""
            out.append(struct.pack(">BH", TAG_BEG_COLLECTION, len(nm)) + nm
                       + struct.pack(">H", 0))
            _encode_collection_body(coll, out)
            out.append(struct.pack(">BHH", TAG_END_COLLECTION, 0, 0))
        return

    for i, value in enumerate(attr.values):
        nm = attr.name.encode("utf-8") if i == 0 else b""
        raw = _encode_value(attr.tag, value)
        out.append(struct.pack(">BH", attr.tag, len(nm)) + nm
                   + struct.pack(">H", len(raw)) + raw)


def _encode_collection_body(coll, out):
    for member, values in coll.items():
        mn = member.encode("utf-8")
        out.append(struct.pack(">BHH", TAG_MEMBER_NAME, 0, len(mn)) + mn)
        if not isinstance(values, Attr):
            raise TypeError("collection members must be Attr, got %r" % type(values))
        attr = values
        if attr.tag == TAG_BEG_COLLECTION:
            for j, sub in enumerate(attr.values):
                if j:
                    out.append(struct.pack(">BHH", TAG_MEMBER_NAME, 0, len(mn)) + mn)
                out.append(struct.pack(">BHH", TAG_BEG_COLLECTION, 0, 0))
                _encode_collection_body(sub, out)
                out.append(struct.pack(">BHH", TAG_END_COLLECTION, 0, 0))
            continue
        for j, value in enumerate(attr.values):
            if j:
                out.append(struct.pack(">BHH", TAG_MEMBER_NAME, 0, len(mn)) + mn)
            raw = _encode_value(attr.tag, value)
            out.append(struct.pack(">BHH", attr.tag, 0, len(raw)) + raw)


def encode(msg):
    out = [struct.pack(">BBHi", msg.version[0], msg.version[1],
                       msg.code, msg.request_id)]
    for group in msg.groups:
        out.append(struct.pack(">B", group.tag))
        for attr in group.attrs:
            _encode_attr(attr, out)
    out.append(struct.pack(">B", TAG_END))
    return b"".join(out)


def member(name, attr):
    """Build a one-member mapping for use inside a Collection."""
    c = Collection()
    c[name] = attr
    return c
