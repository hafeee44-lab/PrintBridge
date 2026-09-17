"""
Turning a PDF into pixels, and working out where those pixels go on paper.

This is the half of printing that has nothing to do with Windows, so it lives
on its own and can be tested anywhere. PDFium does the rasterising - the same
engine Chrome uses - which means the bridge no longer needs a separate PDF
application installed just to put a page on a printer.
"""

from __future__ import annotations

import math

PT_PER_INCH = 72.0
MM_PER_INCH = 25.4

try:
    import pypdfium2 as pdfium
    import pypdfium2.raw as pdfium_raw
    HAVE_PDFIUM = True
except Exception:
    pdfium = pdfium_raw = None
    HAVE_PDFIUM = False


def available():
    return HAVE_PDFIUM


class Placement:
    """Where one page lands on the sheet, in device pixels."""

    def __init__(self, x, y, w, h, rotate=0, scale=1.0):
        self.x, self.y, self.w, self.h = x, y, w, h
        self.rotate = rotate
        self.scale = scale

    def as_tuple(self):
        return (self.x, self.y, self.w, self.h, self.rotate)

    def __repr__(self):
        return ("Placement(x=%d, y=%d, w=%d, h=%d, rotate=%d, scale=%.4f)"
                % (self.x, self.y, self.w, self.h, self.rotate, self.scale))


def place(page_w_pt, page_h_pt, area_w_px, area_h_px, dpi_x, dpi_y,
          mode="none", allow_rotate=True):
    """Work out the rectangle a page should occupy inside the printable area.

    mode:
      none   - exact physical size. A 210mm wide page measures 210mm on paper.
      shrink - actual size, but scaled down if it would not otherwise fit.
      fit    - scaled either way to fill the area, keeping the aspect ratio.

    Rotation is offered when the page and the paper disagree about which way
    round they are, because a landscape page on portrait paper is otherwise
    either tiny or cropped. In 'none' mode it is only used when the page would
    not fit at all - the point of that mode is that nothing is touched.
    """
    if page_w_pt <= 0 or page_h_pt <= 0 or area_w_px <= 0 or area_h_px <= 0:
        raise ValueError("page and area must be positive")

    def natural(rot):
        """size in device px at 1:1, for a given rotation"""
        w_pt, h_pt = (page_h_pt, page_w_pt) if rot else (page_w_pt, page_h_pt)
        return w_pt / PT_PER_INCH * dpi_x, h_pt / PT_PER_INCH * dpi_y

    options = [0, 90] if allow_rotate else [0]
    best = None

    for rot in options:
        nat_w, nat_h = natural(rot)
        fit = min(area_w_px / nat_w, area_h_px / nat_h)
        if mode == "fit":
            scale = fit
        elif mode == "shrink":
            scale = min(1.0, fit)
        else:                                   # none / actual size
            scale = 1.0
        w, h = nat_w * scale, nat_h * scale
        overflow = max(0.0, w - area_w_px) + max(0.0, h - area_h_px)
        # prefer no overflow, then the larger print
        key = (overflow > 0.5, overflow, -(w * h))
        if best is None or key < best[0]:
            best = (key, rot, scale, w, h)

    _, rot, scale, w, h = best

    if mode == "none" and rot == 90:
        # only rotate in actual-size mode when upright genuinely does not fit
        up_w, up_h = natural(0)
        if up_w <= area_w_px + 0.5 and up_h <= area_h_px + 0.5:
            rot, w, h = 0, up_w, up_h

    x = (area_w_px - w) / 2.0
    y = (area_h_px - h) / 2.0
    return Placement(int(round(x)), int(round(y)),
                     max(1, int(round(w))), max(1, int(round(h))),
                     rot, scale)


class Document:
    """A PDF open for rendering. Use as a context manager."""

    def __init__(self, path):
        if not HAVE_PDFIUM:
            raise RuntimeError("pypdfium2 is not installed")
        self._doc = pdfium.PdfDocument(path)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False

    def close(self):
        try:
            self._doc.close()
        except Exception:
            pass

    def __len__(self):
        return len(self._doc)

    def page_size(self, index):
        """(width, height) in PDF points, with any /Rotate already applied."""
        page = self._doc[index]
        try:
            return page.get_size()
        finally:
            page.close()

    def page_sizes(self):
        return [self.page_size(i) for i in range(len(self._doc))]

    def scale_for(self, index, placement):
        """The pdfium scale factor that renders this page at placement size."""
        w_pt, h_pt = self.page_size(index)
        if placement.rotate in (90, 270):
            w_pt = h_pt
        if w_pt <= 0:
            return 1.0
        return max(0.01, placement.w / float(w_pt))

    def render(self, index, scale, rotation=0, grayscale=False):
        """Rasterise one page at a given scale, already turned the right way up.

        Rotation happens here rather than later because a device context
        cannot turn a bitmap round. Returns a Raster - see that class for why
        it is an object rather than a plain buffer.
        """
        page = self._doc[index]
        try:
            bitmap = page.render(
                scale=scale,
                rotation=rotation,
                force_bitmap_format=pdfium_raw.FPDFBitmap_BGRx,
                fill_color=(255, 255, 255, 255),
                grayscale=grayscale,
                draw_annots=True,
            )
            return Raster(bitmap)
        finally:
            page.close()


class Raster:
    """One rendered page, kept where it was drawn.

    The buffer is a ctypes array pointing straight at PDFium's own memory, so
    it can be handed to the graphics layer without being copied first. An A4
    page at 600dpi is 139MB; copying that for every sheet is the difference
    between working and thrashing on an old machine. The catch is that the
    buffer only stays valid while this object is alive, hence the class.

    32-bit BGRX, top row first, every row a multiple of four bytes.
    """

    def __init__(self, bitmap):
        self._bitmap = bitmap
        self.buffer = bitmap.buffer          # ctypes array, not a copy
        self.width = bitmap.width
        self.height = bitmap.height
        self.stride = bitmap.stride

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()
        return False

    def close(self):
        self.buffer = None
        try:
            self._bitmap.close()
        except Exception:
            pass
        self._bitmap = None

    def tobytes(self):
        return bytes(self.buffer)

    def __repr__(self):
        return "Raster(%dx%d, stride=%d)" % (self.width, self.height, self.stride)


def scale_for_dpi(dpi):
    return dpi / PT_PER_INCH


def mm_to_px(mm, dpi):
    return mm / MM_PER_INCH * dpi


def pt_to_mm(pt):
    return pt / PT_PER_INCH * MM_PER_INCH


# ---------------------------------------------------------------------------
# images
#
# A phone printing a photo over AirPrint sends a JPEG, not a PDF, and PDFium
# only opens PDFs. Wrapping the JPEG in a one-page PDF is cheap and lossless -
# the compressed bytes go in untouched as a DCTDecode stream, so there is no
# decoding, no re-encoding and no second imaging library to install.
# ---------------------------------------------------------------------------

JPEG_SOF_MARKERS = set(range(0xC0, 0xD0)) - {0xC4, 0xC8, 0xCC}


def jpeg_size(data):
    """(width, height, components) of a JPEG, or None if it is not one."""
    if len(data) < 4 or data[0] != 0xFF or data[1] != 0xD8:
        return None
    i, n = 2, len(data)
    while i + 3 < n:
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
            i += 2
            continue
        if marker == 0xD9 or marker == 0xDA:      # end, or start of scan
            break
        if i + 3 >= n:
            break
        length = (data[i + 2] << 8) | data[i + 3]
        if length < 2:
            break
        if marker in JPEG_SOF_MARKERS and i + 9 < n:
            height = (data[i + 5] << 8) | data[i + 6]
            width = (data[i + 7] << 8) | data[i + 8]
            comps = data[i + 9]
            if width and height:
                return width, height, comps
        i += 2 + length
    return None


def jpeg_to_pdf(data, page_w_mm=210.0, page_h_mm=297.0, margin_mm=10.0):
    """Wrap JPEG bytes in a one-page PDF, the image centred and fitted.

    Returns PDF bytes, or None if the data is not a JPEG this can describe.
    """
    info = jpeg_size(data)
    if not info:
        return None
    px_w, px_h, comps = info
    space = "/DeviceCMYK" if comps == 4 else ("/DeviceGray" if comps == 1
                                              else "/DeviceRGB")

    avail_w = max(1.0, page_w_mm - 2 * margin_mm)
    avail_h = max(1.0, page_h_mm - 2 * margin_mm)
    ratio = px_w / float(px_h)
    w_mm = avail_w
    h_mm = w_mm / ratio
    if h_mm > avail_h:
        h_mm = avail_h
        w_mm = h_mm * ratio

    to_pt = PT_PER_INCH / MM_PER_INCH
    page_w, page_h = page_w_mm * to_pt, page_h_mm * to_pt
    draw_w, draw_h = w_mm * to_pt, h_mm * to_pt
    x = (page_w - draw_w) / 2.0
    y = (page_h - draw_h) / 2.0

    content = ("q\n%.4f 0 0 %.4f %.4f %.4f cm\n/Im0 Do\nQ\n"
               % (draw_w, draw_h, x, y)).encode("ascii")

    out = bytearray()
    offsets = {}

    def obj(num, body, stream=None):
        offsets[num] = len(out)
        out.extend(("%d 0 obj\n%s\n" % (num, body)).encode("ascii"))
        if stream is not None:
            out.extend(b"stream\n")
            out.extend(stream)
            out.extend(b"\nendstream\n")
        out.extend(b"endobj\n")

    out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    obj(1, "<< /Type /Catalog /Pages 2 0 R >>")
    obj(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    obj(3, "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.4f %.4f] "
           "/Resources << /XObject << /Im0 5 0 R >> /ProcSet [/PDF /ImageC] >> "
           "/Contents 4 0 R >>" % (page_w, page_h))
    obj(4, "<< /Length %d >>" % len(content), content)
    obj(5, "<< /Type /XObject /Subtype /Image /Width %d /Height %d "
           "/ColorSpace %s /BitsPerComponent 8 /Filter /DCTDecode /Length %d >>"
           % (px_w, px_h, space, len(data)), data)

    start = len(out)
    out.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for num in range(1, 6):
        out.extend(("%010d 00000 n \n" % offsets[num]).encode("ascii"))
    out.extend(("trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                % start).encode("ascii"))
    return bytes(out)


def images_to_pdf(pages):
    """Several JPEGs into one PDF, each page the true size of its image.

    pages is a list of (jpeg_bytes, dpi). A scan is already a physical thing -
    2480 pixels at 300dpi is 210mm of paper - so the page is made that size
    rather than dropped onto A4 with a guessed margin. Print it at actual size
    and what comes out matches what went on the glass.

    Returns PDF bytes, or None if none of the images could be described.
    """
    usable = []
    for data, dpi in pages:
        info = jpeg_size(data)
        if not info or not dpi or dpi <= 0:
            continue
        px_w, px_h, comps = info
        usable.append((data, px_w, px_h, comps,
                       px_w / float(dpi) * PT_PER_INCH,
                       px_h / float(dpi) * PT_PER_INCH))
    if not usable:
        return None

    out = bytearray()
    offsets = {}

    def obj(num, body, stream=None):
        offsets[num] = len(out)
        out.extend(("%d 0 obj\n%s\n" % (num, body)).encode("ascii"))
        if stream is not None:
            out.extend(b"stream\n")
            out.extend(stream)
            out.extend(b"\nendstream\n")
        out.extend(b"endobj\n")

    count = len(usable)
    first_page = 3
    kids = " ".join("%d 0 R" % (first_page + i * 3) for i in range(count))

    out.extend(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    obj(1, "<< /Type /Catalog /Pages 2 0 R >>")
    obj(2, "<< /Type /Pages /Kids [%s] /Count %d >>" % (kids, count))

    for i, (data, px_w, px_h, comps, w_pt, h_pt) in enumerate(usable):
        page_no = first_page + i * 3
        content_no, image_no = page_no + 1, page_no + 2
        space = "/DeviceCMYK" if comps == 4 else ("/DeviceGray" if comps == 1
                                                  else "/DeviceRGB")
        content = ("q\n%.4f 0 0 %.4f 0 0 cm\n/Im0 Do\nQ\n"
                   % (w_pt, h_pt)).encode("ascii")
        obj(page_no,
            "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.4f %.4f] "
            "/Resources << /XObject << /Im0 %d 0 R >> /ProcSet [/PDF /ImageC] >> "
            "/Contents %d 0 R >>" % (w_pt, h_pt, image_no, content_no))
        obj(content_no, "<< /Length %d >>" % len(content), content)
        obj(image_no,
            "<< /Type /XObject /Subtype /Image /Width %d /Height %d "
            "/ColorSpace %s /BitsPerComponent 8 /Filter /DCTDecode /Length %d >>"
            % (px_w, px_h, space, len(data)), data)

    total = first_page + count * 3
    start = len(out)
    out.extend(("xref\n0 %d\n0000000000 65535 f \n" % total).encode("ascii"))
    for num in range(1, total):
        out.extend(("%010d 00000 n \n" % offsets[num]).encode("ascii"))
    out.extend(("trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                % (total, start)).encode("ascii"))
    return bytes(out)


def test_page_pdf(page_w_mm=210.0, page_h_mm=297.0):
    """A page you can hold a ruler against.

    No text, so no font has to be embedded: a border 10mm in from every edge,
    a 100mm square dead centre, and tick marks every 10mm along the top. If
    the square measures 100mm the whole placement chain is right, and if the
    border is even the page is not being silently scaled.
    """
    to_pt = PT_PER_INCH / MM_PER_INCH
    W, H = page_w_mm * to_pt, page_h_mm * to_pt

    ops = ["0.6 w", "0 G"]
    m = 10.0 * to_pt
    ops.append("%.3f %.3f %.3f %.3f re S" % (m, m, W - 2 * m, H - 2 * m))

    side = 100.0 * to_pt
    ops.append("1.2 w")
    ops.append("%.3f %.3f %.3f %.3f re S" % ((W - side) / 2, (H - side) / 2, side, side))

    ops.append("0.4 w")
    for i in range(0, int(page_w_mm // 10) + 1):
        x = i * 10.0 * to_pt
        length = (6.0 if i % 5 else 11.0) * to_pt
        ops.append("%.3f %.3f m %.3f %.3f l S" % (x, H, x, H - length))
    for i in range(0, int(page_h_mm // 10) + 1):
        y = H - i * 10.0 * to_pt
        length = (6.0 if i % 5 else 11.0) * to_pt
        ops.append("0 %.3f m %.3f %.3f l S" % (y, length, y))

    ops.append("0.15 0.35 0.75 RG")
    ops.append("2 w")
    for cx, cy in ((m, m), (W - m, m), (m, H - m), (W - m, H - m)):
        ops.append("%.3f %.3f m %.3f %.3f l S" % (cx - 8, cy, cx + 8, cy))
        ops.append("%.3f %.3f m %.3f %.3f l S" % (cx, cy - 8, cx, cy + 8))

    content = ("\n".join(ops) + "\n").encode("ascii")

    out = bytearray()
    offsets = {}

    def obj(num, body, stream=None):
        offsets[num] = len(out)
        out.extend(("%d 0 obj\n%s\n" % (num, body)).encode("ascii"))
        if stream is not None:
            out.extend(b"stream\n")
            out.extend(stream)
            out.extend(b"\nendstream\n")
        out.extend(b"endobj\n")

    out.extend(b"%PDF-1.4\n")
    obj(1, "<< /Type /Catalog /Pages 2 0 R >>")
    obj(2, "<< /Type /Pages /Kids [3 0 R] /Count 1 >>")
    obj(3, "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.4f %.4f] "
           "/Resources << /ProcSet [/PDF] >> /Contents 4 0 R >>" % (W, H))
    obj(4, "<< /Length %d >>" % len(content), content)
    start = len(out)
    out.extend(b"xref\n0 5\n0000000000 65535 f \n")
    for num in range(1, 5):
        out.extend(("%010d 00000 n \n" % offsets[num]).encode("ascii"))
    out.extend(("trailer\n<< /Size 5 /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
                % start).encode("ascii"))
    return bytes(out)
