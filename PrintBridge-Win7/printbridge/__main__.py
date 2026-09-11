"""Command line entry point:  python -m printbridge"""

from __future__ import annotations

import argparse
import os
import signal
import socket
import sys
import threading
import time

from . import __version__, backend as backend_mod, discovery, model, server

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


def main(argv=None):
    args = parse_args(argv)
    script_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

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
                             log=log)

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
        )
        svc.add_queue(q)

    # bind
    httpd = None
    for attempt in range(5):
        try:
            httpd = server.Server(("0.0.0.0", port), svc,
                                  web_dir=os.path.join(script_dir, "web"),
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
        advertised = adv.start(svc.queues, ip, port, pin=bool(args.pin))
        httpd.airprint_names = adv.names

    log("  Sharing:")
    for q in svc.queues:
        log("    %-40s  %s" % (q.printer_name, q.uri))
    log()
    log("  Printing method: %s" % be.method)
    if be.method not in ("sumatrapdf", "simulate"):
        log("  ! SumatraPDF was not found, so every job is handed to whatever")
        log("    app owns the PrintTo verb. If nothing does, jobs fail with")
        log("    \"no PDF handler available\". Download SumatraPDF portable and")
        log("    put SumatraPDF.exe in this folder, then restart.")
    if advertised:
        log("  Bonjour: advertised, so 'Share -> Print' on your phone should")
        log("           list the printer with no setup at all.")
    else:
        log("  Bonjour: not advertising. Use the web page below instead.")
    if args.pin:
        log("  PIN required: %s" % args.pin)
    if args.simulate:
        log("  SIMULATION - nothing will actually print.")
    log()
    log("  Web page (any device on the same WiFi):")
    log("      http://%s:%d" % (ip, port))
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
