"""Command line entry point:  python -m printbridge"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import tempfile
import threading
import time

from . import (__version__, backend as backend_mod, discovery, model, scan,
               server, tray, winprint)

BANNER = r"""
  ___     _     _   ___     _    _
 | _ \_ _(_)_ _| |_| _ )_ _(_)__| |__ _ ___
 |  _/ '_| | ' \  _| _ \ '_| / _` / _` / -_)
 |_| |_| |_|_||_\__|___/_| |_\__,_\__, \___|
                                  |___/      v%s
""" % __version__


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        prog="printbridge",
        description="Share a USB printer to iPhones, Androids and laptops "
                    "over WiFi, using this PC's printer driver.")
    p.add_argument("--port", type=int, default=631,
                   help="TCP port to serve IPP and the web page on "
                        "(default 631, the standard printing port)")
    p.add_argument("--printer", action="append", default=[],
                   help="Windows printer to share. Repeat for more than one. "
                        "Default: the system default printer.")
    p.add_argument("--all-printers", action="store_true",
                   help="share every installed printer")
    p.add_argument("--name", default="",
                   help="the name phones will see (default: the printer's own)")
    p.add_argument("--location", default="", help="shown next to the printer")
    p.add_argument("--pin", default="", help="require this code before printing")
    p.add_argument("--ip", default="", help="advertise this address explicitly")
    p.add_argument("--clear-queue", action="store_true",
                   help="cancel everything waiting on the printer and take it "
                        "off pause, then exit")
    p.add_argument("--test-page", action="store_true",
                   help="print one measurable test page and exit - the fastest "
                        "way to tell whether printing works at all")
    p.add_argument("--debug-print", action="store_true",
                   help="log what the printer driver is told and what it says back")
    p.add_argument("--tray", action="store_true",
                   help="sit in the notification area instead of holding a "
                        "console window open (Windows)")
    p.add_argument("--no-scanner", action="store_true",
                   help="do not offer the scanner, even if this PC has one")
    p.add_argument("--no-discovery", action="store_true",
                   help="skip mDNS; the web page still works")
    p.add_argument("--simulate", action="store_true",
                   help="print nothing - save each job into simulated-jobs/")
    p.add_argument("--list", action="store_true",
                   help="list installed printers and exit")
    p.add_argument("--brand", default="",
                   help="manufacturer to report. Set it to something neutral "
                        "like Generic if a vendor's phone plugin keeps trying "
                        "to claim the printer and then fails to print.")
    p.add_argument("--log-file", default="",
                   help="also append everything printed here to a file")
    p.add_argument("--max-mb", type=int, default=200,
                   help="largest single job to accept (default 200 MB)")
    return p.parse_args(argv)


def choose_printers(args, log):
    installed = backend_mod.list_printers(simulate=args.simulate)
    if not installed:
        return []
    if args.all_printers:
        return installed
    if args.printer:
        chosen = []
        by_lower = {p.name.lower(): p for p in installed}
        for want in args.printer:
            hit = by_lower.get(want.lower())
            if hit is None:
                for p in installed:
                    if want.lower() in p.name.lower():
                        hit = p
                        break
            if hit is None:
                log("  ! no printer matching %r - ignoring it" % want)
            else:
                chosen.append(hit)
        if chosen:
            return chosen
    d = backend_mod.default_printer(installed)
    if d is not None:
        log("  Printer:    %s%s" % (d.name, "  (Windows default)" if d.default
                                   else "  (picked automatically)"))
        if backend_mod.is_virtual(d):
            log("  ! That is a virtual printer - it writes a file instead of")
            log("    printing. Windows reported these printers:")
            for x in installed:
                log("      %-40s %s" % (x.name, x.port or "?"))
            log("    Install the printer's Windows driver, or start with")
            log("      Start Print Bridge.bat --printer \"<name>\"")
        else:
            others = [p.name for p in installed
                      if p is not d and not backend_mod.is_virtual(p)]
            if others:
                log("    Other printers: %s" % ", ".join(others))
                log("    Share one of those instead with:")
                log("      Start Print Bridge.bat --printer \"<name>\"")
    return [d] if d else []


def paths():
    """Where the code is, and where its files belong.

    Built into a single .exe these are not the same place: PyInstaller unpacks
    the code and the web page into a temporary folder that disappears on exit,
    while the log, the spool and any SumatraPDF.exe belong next to the
    executable where somebody can actually find them.
    """
    if getattr(sys, "frozen", False):
        bundle = getattr(sys, "_MEIPASS",
                         os.path.dirname(os.path.abspath(sys.executable)))
        return bundle, os.path.dirname(os.path.abspath(sys.executable))
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return here, here


def test_page(be, printer, log):
    """Print one page with a ruler on it, and say exactly what happened."""
    from . import render as render_mod

    log("  Test page")
    log("  " + "-" * 60)
    log("  Printer:  %s" % printer.name)
    log("  Method:   %s  (%s)" % (be.method, be.method_detail))
    if not render_mod.available():
        log("  ! The PDF engine is missing. Run:  pip install pypdfium2")

    path = os.path.join(tempfile.gettempdir(), "printbridge-testpage.pdf")
    try:
        with open(path, "wb") as fh:
            fh.write(render_mod.test_page_pdf())
    except OSError as e:
        log("  ! could not write the test page: %s" % e)
        return 3

    before = winprint.describe_printer(printer.name)
    if before:
        log("  State:    %s" % before)

    be.debug = True
    result = be.print_file(path, printer.name, scale="noscale",
                           label="Print Bridge test page")
    log()
    if result.ok:
        log("  Sent. (%s: %s)" % (result.method, result.detail))
        log()
        log("  On the sheet you should find:")
        log("    - a border 10mm in from every edge, even on all four sides")
        log("    - a square in the middle measuring exactly 100mm")
        log("    - ticks every 10mm along the top and left")
        log()
        after = winprint.describe_printer(printer.name)
        if after:
            log("  The printer says: %s" % after)
        log()
        log("  If the square measures 100mm, sizing is right.")
        log("  If nothing comes out and the job sits in the queue, the")
        log("  spooler took it and the printer is not drawing it down:")
        log("    - cancel everything in Devices and Printers")
        log("    - switch the printer off, wait, switch it on")
        log("    - make sure it is not set to 'Use Printer Offline'")
    else:
        log("  FAILED: %s" % result.detail)
        log("  (method tried: %s)" % result.method)
    try:
        os.unlink(path)
    except OSError:
        pass
    return 0 if result.ok else 1


def main(argv=None):
    args = parse_args(argv)
    bundle_dir, script_dir = paths()

    logf = None
    if args.log_file:
        try:
            if (os.path.exists(args.log_file)
                    and os.path.getsize(args.log_file) > 2 * 1024 * 1024):
                os.replace(args.log_file, args.log_file + ".old")
            logf = open(args.log_file, "a", encoding="utf-8", errors="replace")
        except OSError:
            logf = None

    def log(msg=""):
        print(msg, flush=True)
        if logf is not None:
            try:
                logf.write("%s %s\n" % (time.strftime("%H:%M:%S"), msg))
                logf.flush()
            except (OSError, ValueError):
                pass

    if args.list:
        for p in backend_mod.list_printers(simulate=args.simulate):
            tags = []
            if p.default:
                tags.append("default")
            if p.offline:
                tags.append("offline")
            if backend_mod.is_virtual(p):
                tags.append("virtual")
            if p.duplex:
                tags.append("duplex")
            log("%-42s %-14s %s%s" % (p.name, p.port, p.driver,
                                      "   [%s]" % ", ".join(tags) if tags else ""))
        return 0

    log(BANNER)
    log("  by Hafi (@hafeee44-lab)  -  MIT licence")
    log()
    log("  Folder:     %s" % script_dir)

    printers = choose_printers(args, log)
    if not printers:
        log("  No printers are installed on this PC.")
        log("  Install the printer's Windows driver first, print a test page,")
        log("  then start PrintBridge again.")
        return 2

    be = backend_mod.Backend(script_dir, simulate=args.simulate,
                             job_dir=os.path.join(script_dir, "simulated-jobs"),
                             log=log, debug=args.debug_print)

    if args.clear_queue:
        ok, detail = winprint.clear_queue(printers[0].name, log=log)
        log("  %s" % detail)
        return 0 if ok else 1

    if args.test_page:
        return test_page(be, printers[0], log)
    if bundle_dir != script_dir:
        log("  Bundled:    running as a single executable")

    ip = args.ip or discovery.local_ip()
    port = args.port

    svc = server.Service(be, spool_dir=os.path.join(script_dir, "spool"),
                         pin=args.pin, log=log,
                         max_bytes=max(1, args.max_mb) * 1024 * 1024)

    for i, p in enumerate(printers):
        q = model.Queue(
            p.name, be, host=ip, port=port,
            dns_name=(args.name if (args.name and len(printers) == 1) else p.name),
            resource="/ipp/print" if len(printers) == 1
                     else "/ipp/print/" + model.slugify(p.name),
            location=args.location, log=log, brand=args.brand,
            make_and_model=(args.name if (args.name and len(printers) == 1)
                            else p.name),
            duplex=p.duplex,
        )
        svc.add_queue(q)

    # bind
    httpd = None
    for attempt in range(5):
        try:
            httpd = server.Server(("0.0.0.0", port), svc,
                                  web_dir=os.path.join(bundle_dir, "web"),
                                  advertised_host=ip)
            break
        except OSError as e:
            log("  port %d is not available (%s)" % (port, e))
            port += 1
    if httpd is None:
        log("  Could not bind any port between %d and %d." % (args.port, port))
        return 3
    if port != args.port:
        log("  using port %d instead" % port)
        svc.set_host(ip, port)

    adv = discovery.Advertiser(log=log)
    advertised = False
    if not args.no_discovery:
        found_scanner = None if args.no_scanner else svc.find_scanner()
        advertised = adv.start(svc.queues, ip, port, pin=bool(args.pin),
                               scanner=found_scanner)
        httpd.airprint_names = adv.names

    for p_ in printers:
        trouble = winprint.describe_printer(p_.name)
        if trouble:
            log("  ! %s: %s" % (p_.name, trouble))
            if "waiting" in trouble and "job" in trouble:
                log("    Jobs are queued but not coming out. Cancel them in")
                log("    Devices and Printers, then switch the printer off and")
                log("    on - this model wedges after an interrupted job.")

    log("  Sharing:")
    for q in svc.queues:
        log("    %-40s  %s" % (q.printer_name, q.uri))
    log()
    two_sided = any(q.duplex_capable for q in svc.queues)
    log("  Both sides: %s" % (
        "the printer does it itself, so phones offer it"
        if two_sided else
        "no duplexer - use the web page's manual two-pass"))
    log("  Printing: %s  (%s)" % (be.method, be.method_detail))
    if be.method == "sumatrapdf":
        log("    Install pypdfium2 to drop the SumatraPDF dependency and get")
        log("    exact sizing and duplex control:  pip install pypdfium2")
    if be.method not in ("native", "sumatrapdf", "simulate"):
        log("  ! SumatraPDF was not found, so every job is handed to whatever")
        log("    app owns the PrintTo verb. If nothing does, jobs fail with")
        log("    \"no PDF handler available\". Download SumatraPDF portable and")
        log("    put SumatraPDF.exe in this folder, then restart.")
    if advertised:
        log("  Bonjour: advertised, so 'Share -> Print' on your phone should")
        log("           list the printer with no setup at all.")
    if adv.scanner_name:
        log("  Scanner: %s" % adv.scanner_name)
        log("           iPhone: Files -> ... -> Scan Documents.")
        log("           Android: any app that uses Mopria Scan.")
    elif not args.no_scanner and svc.find_scanner() is None:
        log("  Scanner: none found on this PC (printing is unaffected)")
    else:
        log("  Bonjour: not advertising. Use the web page below instead.")
    if args.pin:
        log("  PIN required: %s" % args.pin)
    if args.simulate:
        log("  SIMULATION - nothing will actually print.")
    log()
    log("  Web page (any device on the same WiFi):")
    log("      http://%s:%d" % (ip, port))
    if advertised and adv.local_name:
        log("      http://%s:%d   <- same page, and this name keeps working"
            % (adv.local_name, port))
        log("         even when the router hands this PC a different address.")
    log()
    for iface, cat in backend_mod.network_profiles():
        if cat == "Public":
            log("  ! Windows treats \"%s\" as a Public network, and the firewall"
                % iface)
            log("    rules only cover Private ones. Settings -> Network -> WiFi ->")
            log("    your network -> set the profile to Private, or phones will")
            log("    not be able to reach this PC.")
            log()
            break

    if args.log_file:
        log("  Running in the background. \"Stop Starting With Windows.bat\"")
        log("  removes it and stops it.")
    else:
        log("  Leave this window open while you print. Ctrl-C to stop.")
    log("  " + "-" * 60)

    stop = threading.Event()

    def bye(*_):
        stop.set()

    signal.signal(signal.SIGINT, bye)
    try:
        signal.signal(signal.SIGTERM, bye)
    except (AttributeError, ValueError):
        pass

    t = threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.4},
                         daemon=True)
    t.start()

    icon = None
    if args.tray and tray.available():
        found = None if args.no_scanner else svc.find_scanner()
        icon = tray.Tray(
            script_dir,
            url="http://%s:%d" % (ip, port),
            printer=printers[0].name if printers else "",
            scanner=found.name if found else "",
            log_path=args.log_file or "",
            on_quit=stop.set,
            on_clear=(lambda: winprint.clear_queue(printers[0].name, log=log))
                     if printers else None,
        )
        log("  Tray: showing an icon next to the clock")

    # The tray owns the wait when it is up - its message loop is the main
    # thread's job. If it could not start, fall back to simply waiting.
    if icon is None or not icon.run():
        try:
            while not stop.is_set():
                time.sleep(0.3)
        except KeyboardInterrupt:
            pass

    log("\n  stopping...")
    adv.stop()
    httpd.shutdown()
    svc.shutdown()
    log("  bye.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
