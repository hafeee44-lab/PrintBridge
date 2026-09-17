"""The parts that can be checked without a printer attached.

Everything here is arithmetic, parsing or file format work - the places a
quiet mistake would go unnoticed until something came out the wrong size.
The Windows-only layers (GDI, WIA) are exercised through their guards only,
because they need hardware.
"""

import io
import os
import struct
import sys
import unittest
import xml.dom.minidom as minidom

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from printbridge import backend, escl, icons, render, scan, winprint  # noqa: E402

MM = 72 / 25.4
A4_PT = (210 * MM, 297 * MM)


def _jpeg(width, height, colour=(200, 200, 200)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (width, height), colour).save(buf, "JPEG", quality=70)
    return buf.getvalue()


class PageSelection(unittest.TestCase):
    def test_all_pages_by_default(self):
        self.assertEqual(backend.selected_pages(4), [1, 2, 3, 4])

    def test_odd_and_even(self):
        self.assertEqual(backend.selected_pages(6, subset="odd"), [1, 3, 5])
        self.assertEqual(backend.selected_pages(6, subset="even"), [2, 4, 6])

    def test_range_and_subset_intersect(self):
        self.assertEqual(backend.selected_pages(6, pages="1-4", subset="odd"), [1, 3])

    def test_reverse_keeps_the_selection(self):
        self.assertEqual(
            backend.selected_pages(6, pages="1-4", subset="even", reverse=True), [4, 2])

    def test_out_of_range_is_dropped(self):
        self.assertEqual(backend.selected_pages(3, pages="7-9"), [])

    def test_no_pages_at_all(self):
        self.assertEqual(backend.selected_pages(0), [])


class VirtualPrinters(unittest.TestCase):
    def make(self, name, driver="", port=""):
        return backend.Printer(name, driver=driver, port=port)

    def test_windows_fakes_are_virtual(self):
        for name in ("Microsoft XPS Document Writer", "Microsoft Print to PDF",
                     "Fax", "OneNote (Desktop)", "Adobe PDF"):
            self.assertTrue(backend.is_virtual(self.make(name)), name)

    def test_real_hardware_is_not(self):
        for name in ("HP LaserJet Professional M1132 MFP", "EPSON L3150 Series",
                     "Canon LBP2900", "Brother HL-1110"):
            self.assertFalse(backend.is_virtual(self.make(name)), name)

    def test_port_gives_it_away(self):
        self.assertTrue(backend.is_virtual(self.make("Some Writer", port="PORTPROMPT:")))

    def test_real_hardware_beats_the_default_flag(self):
        xps = backend.Printer("Microsoft XPS Document Writer", default=True,
                              port="XPSPort:")
        hp = backend.Printer("HP LaserJet M1132", port="USB001")
        self.assertIs(backend.default_printer([xps, hp]), hp)

    def test_falls_back_when_nothing_real_exists(self):
        xps = backend.Printer("Microsoft XPS Document Writer", default=True)
        self.assertIs(backend.default_printer([xps]), xps)

    def test_offline_is_skipped(self):
        off = backend.Printer("HP LaserJet M1132", default=True, offline=True)
        on = backend.Printer("EPSON L3150")
        self.assertIs(backend.default_printer([off, on]), on)


class Placement(unittest.TestCase):
    DPI = 600
    AREA = (int(202 / 25.4 * 600), int(289 / 25.4 * 600))

    def place(self, w_pt, h_pt, mode):
        return render.place(w_pt, h_pt, self.AREA[0], self.AREA[1],
                            self.DPI, self.DPI, mode)

    def test_actual_size_is_actually_actual(self):
        spot = self.place(A4_PT[0], A4_PT[1], "none")
        self.assertAlmostEqual(spot.w / self.DPI * 25.4, 210, delta=0.1)
        self.assertAlmostEqual(spot.h / self.DPI * 25.4, 297, delta=0.1)

    def test_shrink_fits_inside(self):
        spot = self.place(A4_PT[0], A4_PT[1], "shrink")
        self.assertLessEqual(spot.w, self.AREA[0])
        self.assertLessEqual(spot.h, self.AREA[1])

    def test_shrink_never_enlarges(self):
        a5 = (148 * MM, 210 * MM)
        self.assertAlmostEqual(self.place(a5[0], a5[1], "shrink").scale, 1.0, places=6)

    def test_fit_does_enlarge(self):
        a5 = (148 * MM, 210 * MM)
        self.assertGreater(self.place(a5[0], a5[1], "fit").scale, 1.0)

    def test_landscape_rotates_to_fit(self):
        land = (297 * MM, 210 * MM)
        self.assertEqual(self.place(land[0], land[1], "shrink").rotate, 90)

    def test_actual_size_leaves_a_fitting_page_alone(self):
        a5 = (148 * MM, 210 * MM)
        self.assertEqual(self.place(a5[0], a5[1], "none").rotate, 0)

    def test_actual_size_still_rotates_when_it_must(self):
        land = (297 * MM, 210 * MM)
        self.assertEqual(self.place(land[0], land[1], "none").rotate, 90)

    def test_centred(self):
        a5 = (148 * MM, 210 * MM)
        spot = self.place(a5[0], a5[1], "none")
        self.assertAlmostEqual(spot.x * 2 + spot.w, self.AREA[0], delta=2)
        self.assertAlmostEqual(spot.y * 2 + spot.h, self.AREA[1], delta=2)

    def test_non_square_resolution(self):
        spot = render.place(A4_PT[0], A4_PT[1], 9999, 9999, 600, 300, "none")
        self.assertAlmostEqual(spot.w / 600 * 25.4, 210, delta=0.1)
        self.assertAlmostEqual(spot.h / 300 * 25.4, 297, delta=0.1)

    def test_rejects_nonsense(self):
        with self.assertRaises(ValueError):
            render.place(0, 100, 100, 100, 300, 300, "none")


class PrinterPlan(unittest.TestCase):
    """The sheet-relative arithmetic that decides where a page lands."""

    CAPS = {"dpi_x": 600, "dpi_y": 600, "off_x": 94, "off_y": 94,
            "phys_w": 4960, "phys_h": 7015, "area_w": 4772, "area_h": 6827}

    class FakeDoc:
        def __init__(self, sizes):
            self.sizes = sizes

        def __len__(self):
            return len(self.sizes)

        def page_size(self, index):
            return self.sizes[index]

    def test_actual_size_steps_over_the_unprintable_margin(self):
        doc = self.FakeDoc([A4_PT])
        plan = winprint.plan_pages(doc, self.CAPS, "none")
        self.assertEqual(plan[0]["x"], -self.CAPS["off_x"])
        self.assertEqual(plan[0]["y"], -self.CAPS["off_y"])

    def test_fitting_modes_stay_inside_the_printable_area(self):
        doc = self.FakeDoc([A4_PT])
        plan = winprint.plan_pages(doc, self.CAPS, "shrink")
        self.assertGreaterEqual(plan[0]["x"], 0)
        self.assertLessEqual(plan[0]["x"] + plan[0]["w"], self.CAPS["area_w"] + 1)

    def test_page_range_is_honoured_and_ordered(self):
        doc = self.FakeDoc([A4_PT] * 5)
        self.assertEqual([p["page"] for p in
                          winprint.plan_pages(doc, self.CAPS, "none", [3, 1])], [3, 1])

    def test_out_of_range_pages_vanish(self):
        doc = self.FakeDoc([A4_PT])
        self.assertEqual(winprint.plan_pages(doc, self.CAPS, "none", [9]), [])

    def test_render_dpi_is_capped(self):
        self.assertEqual(winprint.render_dpi(self.CAPS, 300), 300)
        self.assertEqual(winprint.render_dpi(self.CAPS, 1200), 600)


class Jpeg(unittest.TestCase):
    def test_reads_dimensions(self):
        self.assertEqual(render.jpeg_size(_jpeg(640, 480))[:2], (640, 480))

    def test_tall_image(self):
        self.assertEqual(render.jpeg_size(_jpeg(300, 900))[:2], (300, 900))

    def test_rejects_other_formats(self):
        self.assertIsNone(render.jpeg_size(b"\x89PNG\r\n\x1a\n" + b"\0" * 40))
        self.assertIsNone(render.jpeg_size(b""))

    def test_wraps_into_a_page(self):
        pdf = render.jpeg_to_pdf(_jpeg(1200, 800))
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn(b"DCTDecode", pdf)

    def test_refuses_what_it_cannot_describe(self):
        self.assertIsNone(render.jpeg_to_pdf(b"\x89PNG\r\n\x1a\n"))


class ScanPdf(unittest.TestCase):
    def test_pages_keep_their_real_size(self):
        pdf = render.images_to_pdf([(_jpeg(2480, 3508), 300),
                                    (_jpeg(2022, 1276), 600)])
        self.assertTrue(pdf.startswith(b"%PDF"))
        self.assertIn(b"/Count 2", pdf)
        # 2480px at 300dpi is 210mm; 2022px at 600dpi is 85.6mm
        self.assertIn(b"595.2", pdf)
        self.assertIn(b"242.6", pdf)

    def test_nothing_in_nothing_out(self):
        self.assertIsNone(render.images_to_pdf([]))
        self.assertIsNone(render.images_to_pdf([(b"junk", 300)]))

    def test_zero_dpi_is_ignored(self):
        self.assertIsNone(render.images_to_pdf([(_jpeg(100, 100), 0)]))


class Icon(unittest.TestCase):
    def test_directory_points_at_real_images(self):
        data = icons.ico((16, 32, 48))
        reserved, kind, count = struct.unpack("<HHH", data[:6])
        self.assertEqual((reserved, kind, count), (0, 1, 3))
        offset = 6
        for _ in range(count):
            entry = struct.unpack("<BBBBHHII", data[offset:offset + 16])
            size, at = entry[6], entry[7]
            self.assertEqual(data[at:at + 4], b"\x89PNG")
            self.assertLessEqual(at + size, len(data))
            offset += 16


class Escl(unittest.TestCase):
    def scanner(self, feeder=False):
        return scan.Scanner("wia:test", "Test MFP", resolutions=[150, 300, 600],
                            has_feeder=feeder)

    def test_capabilities_is_valid_xml(self):
        minidom.parseString(escl.capabilities_xml(self.scanner()))

    def test_capabilities_advertises_the_real_resolutions(self):
        doc = minidom.parseString(escl.capabilities_xml(self.scanner()))
        found = [n.firstChild.data for n in doc.getElementsByTagName("scan:XResolution")]
        self.assertEqual(found, ["150", "300", "600"])

    def test_platen_size_is_in_three_hundredths(self):
        doc = minidom.parseString(escl.capabilities_xml(self.scanner()))
        self.assertEqual(doc.getElementsByTagName("scan:MaxWidth")[0].firstChild.data,
                         str(int(8.5 * 300)))

    def test_status_is_valid_xml(self):
        minidom.parseString(escl.status_xml("Idle"))

    def test_settings_are_understood(self):
        body = (b"<scan:ScanSettings><scan:XResolution>600</scan:XResolution>"
                b"<scan:ColorMode>Grayscale8</scan:ColorMode>"
                b"<pwg:DocumentFormat>application/pdf</pwg:DocumentFormat>"
                b"</scan:ScanSettings>")
        got = escl.parse_scan_settings(body)
        self.assertEqual(got["dpi"], 600)
        self.assertEqual(got["mode"], "gray")
        self.assertEqual(got["format"], "application/pdf")

    def test_settings_fall_back_sensibly(self):
        got = escl.parse_scan_settings(b"<nonsense/>")
        self.assertEqual((got["dpi"], got["mode"], got["format"]),
                         (300, "color", "image/jpeg"))

    def test_absurd_resolution_is_clamped(self):
        body = b"<scan:XResolution>99999</scan:XResolution>"
        self.assertLessEqual(escl.parse_scan_settings(body)["dpi"], 1200)


class WiaErrors(unittest.TestCase):
    def test_hresults_become_english(self):
        self.assertEqual(scan._friendly("Exception from HRESULT: 0x80210015"),
                         "no scanner is connected")
        self.assertEqual(scan._friendly("0x80210021"),
                         "there is no paper in the feeder")

    def test_anything_else_is_passed_through(self):
        self.assertEqual(scan._friendly("the lamp exploded"), "the lamp exploded")


class Guards(unittest.TestCase):
    """The Windows-only layers must decline, not explode, everywhere else."""

    def test_modules_import_anywhere(self):
        for module in (winprint, scan, render, escl, icons):
            self.assertTrue(hasattr(module, "__name__"))

    def test_native_printing_declines_off_windows(self):
        if not winprint.IS_WINDOWS:
            self.assertFalse(winprint.available())
            with self.assertRaises(winprint.PrintError):
                winprint.print_pdf("nope.pdf", "nobody")

    def test_scanning_declines_off_windows(self):
        if not scan.IS_WINDOWS:
            self.assertEqual(scan.list_scanners(), [])
            self.assertFalse(scan.scan_page().ok)

    def test_backend_falls_through_rather_than_failing(self):
        be = backend.Backend(".", simulate=False, log=lambda m: None)
        outcome = be._print_native("missing.pdf", "nobody", 1, "", "noscale",
                                   False, False, "", "", False, "long", "x")
        self.assertIsNone(outcome)

    def test_simulate_still_works(self):
        import tempfile
        folder = tempfile.mkdtemp()
        source = os.path.join(folder, "doc.pdf")
        with open(source, "wb") as fh:
            fh.write(b"%PDF-1.4\n")
        be = backend.Backend(folder, simulate=True,
                             job_dir=os.path.join(folder, "jobs"),
                             log=lambda m: None)
        outcome = be.print_file(source, "Any", label="doc.pdf")
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.method, "simulate")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class Win32Signatures(unittest.TestCase):
    """Every ctypes call must declare its argument types.

    Without argtypes, ctypes marshals a Python int as a 32-bit C int. Windows
    handles are pointers, so a job prints perfectly until the OS hands out a
    handle above 0x7FFFFFFF and it dies with "int too long to convert" - which
    is how this was found, on the fourth print of the day. A source scan is
    cruder than a real call, but it runs everywhere and catches the whole class.
    """

    MODULES = ("winprint.py", "tray.py", "backend.py")
    LIBS = r"gdi32|user32|shell32|winspool|kernel32|spool"

    def test_no_undeclared_calls(self):
        import re
        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        for name in self.MODULES:
            with open(os.path.join(here, "printbridge", name),
                      encoding="utf-8") as handle:
                src = handle.read()
            called = set(re.findall(r"\b(?:%s)\.(\w+)\(" % self.LIBS, src))
            called.discard("WinDLL")
            declared = set(re.findall(r"\b(?:%s)\.(\w+)\.argtypes" % self.LIBS, src))
            declared |= set(re.findall(r'\("(\w+)",\s*[\w.]+,\s*\[', src))
            missing = sorted(called - declared)
            self.assertEqual(missing, [],
                             "%s calls these without argtypes: %s"
                             % (name, ", ".join(missing)))


class SpoolHousekeeping(unittest.TestCase):
    def test_stale_spool_files_are_swept(self):
        import tempfile, time as _time
        from printbridge import server as server_mod
        folder = tempfile.mkdtemp()
        old = os.path.join(folder, "pbjob-old.dat")
        recent = os.path.join(folder, "pbjob-new.dat")
        keep = os.path.join(folder, "something-else.txt")
        for path in (old, recent, keep):
            with open(path, "wb") as fh:
                fh.write(b"x")
        os.utime(old, (_time.time() - 99999, _time.time() - 99999))

        be = backend.Backend(folder, simulate=True, log=lambda m: None)
        svc = server_mod.Service(be, spool_dir=folder, log=lambda m: None)
        self.assertFalse(os.path.exists(old), "the stale file should be gone")
        self.assertTrue(os.path.exists(recent), "a fresh one should survive")
        self.assertTrue(os.path.exists(keep), "unrelated files are not ours")
        self.assertEqual(svc.sweep_spool(older_than=0), 1)

    def test_dropping_old_jobs_cleans_their_files(self):
        import tempfile
        from printbridge import model
        folder = tempfile.mkdtemp()
        be = backend.Backend(folder, simulate=True, log=lambda m: None)
        q = model.Queue("T", be, log=lambda *a: None)
        try:
            first = q.new_job("a", "u", "application/pdf")
            path = os.path.join(folder, "orphan.pdf")
            with open(path, "wb") as fh:
                fh.write(b"%PDF")
            first.path = path
            for _ in range(205):
                q.new_job("x", "u", "application/pdf")
            self.assertLessEqual(len(q.jobs), 200)
            self.assertFalse(os.path.exists(path),
                             "a dropped job must take its spool file with it")
        finally:
            q.shutdown()


class PrintResultShape(unittest.TestCase):
    def test_carries_pages_and_job_id(self):
        r = backend.PrintResult(True, "ok", "native", pages=3, job_id=42)
        self.assertEqual((r.pages, r.job_id), (3, 42))

    def test_defaults_stay_backwards_compatible(self):
        r = backend.PrintResult(True, "ok", "simulate")
        self.assertEqual((r.pages, r.job_id), (0, 0))


class QueueRecovery(unittest.TestCase):
    def test_clear_queue_declines_politely_off_windows(self):
        if not winprint.IS_WINDOWS:
            ok, detail = winprint.clear_queue("anything")
            self.assertFalse(ok)
            self.assertIn("Windows", detail)

    def test_status_decoder_covers_the_usual_faults(self):
        wanted = {"paused", "offline", "out of paper", "paper jam",
                  "a door is open", "out of toner"}
        known = {text for _bit, text in winprint.PRINTER_STATUS}
        self.assertTrue(wanted <= known, wanted - known)
