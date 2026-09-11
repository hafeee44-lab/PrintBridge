"""
Apple Raster (URF) -> PDF.

iPhones do not send PDF to a printer they consider an AirPrint device; they
render the page themselves and send Apple Raster. So the bridge has to accept
it. Decoding it here and wrapping each page as an image in a PDF lets the
printer's own Windows driver do what it always does, and means an iPhone gets
exactly the page it rendered.

Format: an 8-byte magic and a page count, then per page a 32-byte header and
run-length encoded scan lines. The line encoding is PackBits-like: a leading
byte says how many extra times to repeat the whole line, then within the line
a count < 128 repeats the next pixel, a count > 128 copies literal pixels, and
128 ends the line.

No third-party imaging library: pages go into the PDF as Flate-compressed
DeviceGray or DeviceRGB images, which is all zlib.
"""

from __future__ import annotations

import struct
import zlib

MAGIC = b"UNIRAST\x00"
PAGE_HEADER = 32


class UrfError(Exception):
    pass


class Page:
    __slots__ = ("width", "height", "dpi", "bpp", "gray", "data", "duplex",
                 "quality")

    def __init__(self, width, height, dpi, bpp, gray, duplex=0, quality=0):
        self.width = width
        self.height = height
        self.dpi = dpi or 300
        self.bpp = bpp
        self.gray = gray
        self.duplex = duplex
        self.quality = quality
        self.data = None

    @property
    def points(self):
        """Page size in PDF points."""
        return (self.width * 72.0 / self.dpi, self.height * 72.0 / self.dpi)


def looks_like_urf(head):
    return head[:8] == MAGIC


def _decode_page(buf, pos, page):
    """Run-length decode one page's scan lines. Returns (bitmap, new_pos)."""
    bpp8 = page.bpp // 8
    line_len = page.width * bpp8
    white = b"\xff" * bpp8
    out = bytearray()
    total = line_len * page.height
    end = len(buf)

    rows = 0
    while rows < page.height:
        if pos >= end:
            break
        repeat = buf[pos]
        pos += 1
        line = bytearray()
        while len(line) < line_len:
            if pos >= end:
                break
            n = buf[pos]
            pos += 1
            if n == 0x80:                      # end of line, pad with white
                line += white * ((line_len - len(line)) // bpp8)
                break
            if n < 0x80:                       # repeat the next pixel n+1 times
                px = buf[pos:pos + bpp8]
                pos += bpp8
                if len(px) < bpp8:
                    break
                line += px * (n + 1)
            else:                              # 257-n literal pixels
                count = 257 - n
                take = count * bpp8
                chunk = buf[pos:pos + take]
                pos += take
                line += chunk
        if len(line) < line_len:
            line += white * ((line_len - len(line)) // bpp8)
        del line[line_len:]

        copies = repeat + 1
        if rows + copies > page.height:
            copies = page.height - rows
        out += bytes(line) * copies
        rows += copies

    if len(out) < total:                       # short page: pad rather than fail
        out += b"\xff" * (total - len(out))
    del out[total:]
    return bytes(out), pos


def parse(data):
    """Yield decoded pages from a URF byte string."""
    if not looks_like_urf(data):
        raise UrfError("not Apple Raster")
    if len(data) < 12:
        raise UrfError("truncated Apple Raster")
    count = struct.unpack(">I", data[8:12])[0]
    pos = 12
    pages = []
    for _ in range(count if 0 < count < 10000 else 10000):
        if pos + PAGE_HEADER > len(data):
            break
        (bpp, colorspace, duplex, quality, _u0, _u1,
         width, height, dpi, _u2, _u3) = struct.unpack(
            ">BBBBIIIIIII", data[pos:pos + PAGE_HEADER])
        pos += PAGE_HEADER
        if bpp not in (8, 24) or not width or not height:
            raise UrfError("unsupported raster: %d bpp, %dx%d"
                           % (bpp, width, height))
        if width * height > 200_000_000:
            raise UrfError("page too large to decode")
        page = Page(width, height, dpi, bpp, gray=(bpp == 8),
                    duplex=duplex, quality=quality)
        page.data, pos = _decode_page(data, pos, page)
        pages.append(page)
        if pos >= len(data):
            break
    if not pages:
        raise UrfError("no pages found")
    return pages


# ---------------------------------------------------------------------------
# PDF output
# ---------------------------------------------------------------------------

def to_pdf(pages):
    """Wrap decoded pages as a PDF, one full-bleed image per page."""
    out = bytearray()
    offsets = {}

    def w(b):
        out.extend(b if isinstance(b, bytes) else b.encode("latin-1"))

    def obj(num, body, stream=None):
        offsets[num] = len(out)
        w("%d 0 obj\n" % num)
        w(body)
        w("\n")
        if stream is not None:
            w("stream\n")
            w(stream)
            w("\nendstream\n")
        w("endobj\n")

    w("%PDF-1.4\n%\xe2\xe3\xcf\xd3\n".encode("latin-1"))

    n = len(pages)
    # 1 catalog, 2 pages tree, then per page: page, contents, image
    page_ids = [3 + i * 3 for i in range(n)]

    obj(1, "<< /Type /Catalog /Pages 2 0 R >>")
    obj(2, "<< /Type /Pages /Count %d /Kids [%s] >>"
        % (n, " ".join("%d 0 R" % i for i in page_ids)))

    for i, page in enumerate(pages):
        pid = page_ids[i]
        cid = pid + 1
        iid = pid + 2
        pw, ph = page.points
        content = ("q\n%.4f 0 0 %.4f 0 0 cm\n/Im0 Do\nQ\n" % (pw, ph))
        cbytes = zlib.compress(content.encode("latin-1"), 9)
        obj(pid,
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.4f %.4f] "
            "/Resources << /XObject << /Im0 %d 0 R >> /ProcSet [/PDF /ImageB /ImageC] >> "
            "/Contents %d 0 R >>" % (pw, ph, iid, cid))
        obj(cid, "<< /Length %d /Filter /FlateDecode >>" % len(cbytes), cbytes)
        img = zlib.compress(page.data, 6)
        obj(iid,
            "<< /Type /XObject /Subtype /Image /Width %d /Height %d "
            "/ColorSpace /%s /BitsPerComponent 8 /Filter /FlateDecode "
            "/Length %d >>"
            % (page.width, page.height,
               "DeviceGray" if page.gray else "DeviceRGB", len(img)),
            img)

    last = page_ids[-1] + 2 if pages else 2
    xref_at = len(out)
    w("xref\n0 %d\n" % (last + 1))
    w("0000000000 65535 f \n")
    for i in range(1, last + 1):
        w("%010d 00000 n \n" % offsets.get(i, 0))
    w("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
      % (last + 1, xref_at))
    return bytes(out)


def convert_file(src, dst):
    """URF file -> PDF file. Returns the page count."""
    with open(src, "rb") as fh:
        data = fh.read()
    pages = parse(data)
    with open(dst, "wb") as fh:
        fh.write(to_pdf(pages))
    return len(pages)
