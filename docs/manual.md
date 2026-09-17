<!-- The full guide. The short version is in the repository README. -->

# Print Bridge

Turns this Windows PC into a **wireless printer** for every device in the house.
Turn the PC on, double-click one file, and the HP LaserJet M1132 shows up in your
iPhone's own **Share → Print** sheet — no app, no setup on the phone.

```
iPhone  ─┐   AirPrint
Android ─┼── over WiFi ──▶  Windows PC  ──USB──▶  M1132
laptop  ─┘   (IPP)          (has the HP driver)
```

## Why it has to work this way

The M1132 is a **host-based** printer. It has no page language of its own — it
can't read PCL or PostScript. Whatever machine holds the driver must rasterise
every page into a bitmap stream and push that down the cable.

That rules out the shortcuts: a USB print-server dongle only pipes bytes, and
nothing on the network would be producing the right ones. Your phone can't
render for the M1132 either — no driver exists for it.

So Print Bridge does the honest thing: your phone sends the page over WiFi
using the standard printing protocol (IPP, the same one AirPrint uses), the PC
receives it, and the PC's own HP driver renders and prints it.

Android and macOS send a **PDF**. An iPhone renders the page itself and sends
**Apple Raster** — it will not even list a printer that can't take it — so the
bridge decodes that back into a PDF before handing it to the driver.

---

## Setup — about five minutes, once

### 1. Double-click `Start Print Bridge.bat`

It asks for administrator rights, then walks through everything on its own:

- finds Python, and offers to install it if it's missing
- installs the two libraries it needs: **PDFium**, which turns a PDF into
  pixels at the printer's own resolution, and `zeroconf` for the network
  announcement
- opens the two firewall ports (TCP 631 for printing, UDP 5353 for discovery)

Then it prints something like:

```
  Sharing:
    HP LaserJet Professional M1132 MFP        ipp://192.168.1.42:631/ipp/print

  Bonjour: advertised, so 'Share -> Print' on your phone should
           list the printer with no setup at all.

  Web page (any device on the same WiFi):
      http://192.168.1.42:631
```

Leave that window open while you print. Close it when you're done.

### 2. Print from your phone

**iPhone / iPad** — open anything, **Share → Print**, and pick the printer. It
appears by itself. Nothing to install.

**Android** — most phones find it through the **Mopria Print Service**
(pre-installed on Samsung, Xiaomi, OnePlus and others; otherwise free on the
Play Store). Print from any app's share menu.

**Another Windows PC** — Settings → Printers → Add → *The printer that I want
isn't listed* → **Select a shared printer by name** → paste the
`http://192.168.1.42:631/ipp/print` address.

**Mac** — System Settings → Printers → **+** → it shows up under Default.

### 3. Printing on both sides

A printer with no duplexer cannot turn the paper over by itself, so the web
page walks you through it: set **Both sides** to *On*, print, and it does the
front of every sheet, then stops and tells you to turn the stack over and put
it back. One tap does the rest.

**Flip on** decides which instructions you get, because it changes where the
backs land: *long edge* is a left-to-right turn like a book page, *short edge*
is top-to-bottom like a notepad. Pick the one that matches how you actually
turn the stack.

If the second side comes out in the wrong order, set **Second pass** to
*Reverse order*. Printers stack paper differently and there is no way to know
yours without trying; the reverse option sends the back sides one page at a
time so the running order is certain rather than left to the driver.

Phones only offer a both-sides tick box when the printer really has a
duplexer. The bridge asks the driver and advertises `sides-supported`
accordingly, rather than offering a control that would quietly do nothing.
When a phone picks a binding edge, that choice is carried through as
`duplexlong` or `duplexshort` rather than a generic "duplex" the driver would
resolve however it liked.

### 3a. Card sheets, many copies at exact size

The **Card sheet** tab lays one image out repeatedly on a sheet at a real
physical size: a CNIC, a passport photo, a business card, a raffle ticket,
anything measured in millimetres rather than pixels.

Give it a width and height (or tap a preset), drop in the artwork, and it fills
the sheet: 8 CNICs on an A4, 25 passport photos, and so on, with cut marks in
the margin so a guillotine has something to line up against. The preview is the
real geometry, not an illustration.

Add a **back** image and it produces a second sheet laid out *mirrored*, so
every back lands exactly behind its own front once you turn the stack over.
Which mirror it uses depends on **Flip on**: a long-edge turn mirrors the
columns and keeps the artwork upright, a short-edge turn mirrors the rows and
rotates each card 180 degrees. Get that wrong and the backs end up on the wrong
cards, which is the whole reason the option is there.

Everything is built in the browser. The sheet is assembled into a PDF at exact
millimetre sizes and sent with rescaling switched off, so an 85.6 x 54 mm card
measures 85.6 x 54 mm on paper.

### 4. If a device won't find it — use the web page

Open `http://<the address above>` in any browser. Pick files, choose settings,
print. Add it to your home screen and it behaves like an app. It handles PDFs
and images, several at a time, and it's a useful sanity check when discovery is
being difficult.

The startup banner prints two addresses. The bare IP always works. The second,
`http://printbridge-<pc-name>.local:631`, is the one worth bookmarking - the
bridge answers for that name over mDNS, so it keeps working after the router
hands this PC a different address. iPhones, iPads, Macs and Windows 10 or later
resolve it out of the box; most current Androids do too. If yours doesn't, use
the IP and give the PC a fixed address in your router's DHCP settings.

---

## One file, no window

**In the tray.** Started by `Install Autostart.bat`, Print Bridge runs at every
logon with no console window at all and puts an icon next to the clock.
Right-click it for the address, the folder and the log, or to stop it. Left
click opens the print page.

A Windows *service* would be the obvious-sounding alternative and is the wrong
answer here: services run in session 0, which cannot reach the logged-in
user's printer queue and cannot drive a scanner through WIA. Starting at logon
is not a compromise, it is where this belongs.

**As a single executable.** Run `Build EXE.bat` and you get
`dist\Print Bridge.exe` - one file containing Python, the PDF engine and the
web page. Copy it to a PC that has none of those, double-click, done. The log
and spool sit beside the executable rather than inside it, so they are where
somebody can find them.

The same build runs in CI on every push, so a release always has a working
binary attached rather than only source.

---

## Scanning

A multifunction printer has a scanner under the lid, and it is USB-only for
the same reason the printer was. Print Bridge shares that too.

**From a phone, with nothing installed.** The scanner is announced over
Bonjour as well, using eSCL - the scanning cousin of AirPrint. On an iPhone:
Files, then the dots menu, then **Scan Documents**, and the scanner is in the
list. On Android: anything that uses **Mopria Scan**. Put a page on the glass,
tap, and a PDF arrives on the phone.

**From the web page.** A **Scan** tab appears when the PC has a scanner.
Choose a resolution and colour mode, scan, and pages build up one at a time.
Save the lot as a single PDF, or send it straight back to the printer.

**Straight into a card sheet.** Each scanned page has *Card front* and
*Card back* buttons. Scan a CNIC's front, scan its back, and you are in the
Card sheet tab with both sides loaded and ready to print eight aligned copies.
That is the whole job in one screen rather than four programs.

Pages come out at their true size: 2480 pixels scanned at 300dpi becomes a
210mm page, so printing at actual size reproduces what was on the glass.

Windows drives the hardware through WIA, reached over PowerShell so it works
back to PowerShell 2.0 on Windows 7 with nothing installed. What the scanner
can do - resolutions, colour modes, whether it has a document feeder - is read
from the driver rather than assumed, so the bridge advertises what is actually
there. `--no-scanner` turns the whole thing off.

---

## How it prints

Print Bridge renders PDFs itself, with PDFium - the same engine Chrome uses -
and sends the pages straight to the printer driver through Windows' own
graphics layer. Nothing else has to be installed, and three things follow from
owning that step:

- **Exact physical size.** A page laid out at 210 x 297 mm measures 210 x 297 mm
  on paper. The bridge knows the printer's resolution and the margin it cannot
  reach, and places the page against the sheet rather than against whatever the
  driver felt like.
- **The duplex edge you asked for.** Long or short, passed to the driver as the
  setting it understands.
- **Page order.** Reverse order is one job with the pages in the order wanted,
  not one job per page.

Photos sent from a phone arrive as JPEGs rather than PDFs. Those are wrapped in
a one-page PDF with the compressed bytes passed through untouched - no
decoding, no re-encoding, no second imaging library.

If PDFium is missing the bridge falls back to SumatraPDF, and failing that to
whatever application owns the PrintTo verb. The startup banner says which of
the three is in use, and so does the web page.

---

## When the printer will not print

Some printers - the one this was built around included - stop drawing jobs
down after an interrupted one. Everything after that queues up and nothing
comes out, which looks like a bug in the bridge and is not.

Print Bridge now watches for this rather than leaving you to guess. It asks
the spooler what state the printer is in and says so at startup, before every
job, and on the web page:

    ! HP LaserJet Professional M1132 MFP: 4 jobs already waiting; offline

It knows the usual faults - paused, offline, out of paper, paper jam, door
open, out of toner, needs attention, and "Use Printer Offline". When something
is wrong the web page shows a banner with a **Clear the queue** button, and
there is a matching item in the tray menu. From a console:

    Start Print Bridge.bat --clear-queue

That cancels everything waiting and takes the printer off pause. If it is
offline or in error, switch it off and on afterwards.

### Checking printing on its own

    Start Print Bridge.bat --test-page

Prints one page and exits - no phone, no web page. The page carries a border
10mm from every edge, a 100mm square in the middle and ticks every 10mm, so a
ruler tells you whether sizing is right. Add `--debug-print` to log what the
driver is told and what it answers.

---

## Options

Add arguments after the `.bat`, or edit the file to make them permanent:

| Argument | Effect |
|---|---|
| `--all-printers` | Share every printer installed on this PC, not just the default |
| `--printer "NAME"` | Share a specific printer. Repeat for several. |
| `--name "Study printer"` | The name phones will show |
| `--port 8080` | Use a different port (default 631; it walks forward if taken) |
| `--pin 1234` | Require a code before anything prints |
| `--brand Generic` | Report a neutral manufacturer, so a vendor's phone plugin stops trying to claim the printer |
| `--log-file PATH` | Append everything to a file as well as the window |
| `--simulate` | Print nothing — save each job into `simulated-jobs\`. Good for testing. |
| `--no-discovery` | Skip the network announcement; the web page still works |
| `--list` | Print every installed printer with its port, driver and any `default` / `offline` / `virtual` tags, then exit |

Example: `Start Print Bridge.bat --all-printers --pin 4417`

### Start it with Windows

Double-click **`Install Autostart.bat`** once. It sets up a scheduled task that
starts the bridge at every logon **with no window at all** — nothing to click,
no admin prompt after the first time. It opens the firewall ports too, in case
you've never run the bridge by hand.

Everything it would have printed goes to `printbridge.log` in this folder, so
there's still a record of every job.

To undo it, run **`Stop Starting With Windows.bat`** — that removes the task
and stops anything currently running.

### Print quality and toner

Quality, resolution and toner saving belong to the printer's Windows driver,
not to the bridge and not to your phone — this PC is the machine doing the
rendering, so its driver settings apply to every job that arrives over WiFi.
**`Printer Quality Settings.bat`** opens that dialog directly.

---

## When it doesn't work

| Symptom | What's going on |
|---|---|
| Phone doesn't list the printer | Same WiFi? VPN off? Many routers isolate wireless clients from each other — look for **AP isolation** or **client isolation** and turn it off. |
| iPhone says *No AirPrint printers found* | Turn WiFi off and on to clear its cache, and check no VPN or private-relay profile is active — neither passes the discovery traffic. If it still hides, the console will show whether the phone ever asked; nothing there means the announcement isn't reaching it, which is a network problem rather than a printer one. |
| HP's phone app or print plugin won't print | It only drives real HP hardware, over HP's own protocol — it can't talk to a bridge. In the Android print dialog, tap the printer name and choose the **Mopria** entry rather than the HP one, or turn the HP Print Service Plugin off in *Settings → Connected devices → Printing*. If it keeps grabbing the printer anyway, start the bridge with `--brand Generic` so it stops advertising an HP maker name. |
| Nothing works after a network change | Windows may have flipped the WiFi to a **Public** profile, and the firewall rules only cover Private. Settings → Network → your WiFi → set it to Private. The bridge warns you about this at startup. |
| `could not start mDNS` in the window | Something else already holds port 5353 — usually Apple's Bonjour service, installed by iTunes. Stop the "Bonjour Service" in `services.msc`, or run with `--no-discovery` and use the web page. |
| Shares **Microsoft XPS Document Writer** instead of your printer | Windows installs virtual printers that write a file rather than print, and on a PC where nobody changed it one of those is the system default. The bridge skips them and picks real hardware, so seeing one here means Windows itself has no real printer installed — check *Devices and Printers* and print a Windows test page first. `--list` shows exactly what the bridge can see. |
| Every job fails with *no PDF handler available* | PDFium is missing and nothing on the PC is registered to print a PDF either. Run `Start Print Bridge.bat` again — it installs PDFium — or `python -m pip install pypdfium2`. |
| Prints, but the size is wrong | The job fell back to another PDF application, which rescales. The banner says which method is live; anything other than `native` means PDFium isn't loading. |
| Printer stops mid-job, jobs pile up | The M1132 wedges after a malformed stream. Power-cycle it; queued jobs resume by themselves. |
| Port already in use | It walks forward from 631 by itself. Force one with `--port 8080`. |
| Phone says the printer is offline | The PC is asleep, or the window was closed. Both ends have to be awake. |

The window logs every job — the operation, the file, the size, and whether it
worked. Start there.

---

## About access

Anyone on your WiFi who finds the printer can print to it. They can't read your
files or browse the PC — the bridge serves one page and accepts print jobs, and
nothing else — but they can waste your paper. On a home network that's usually
fine. On shared or office WiFi, use `--pin`.

It listens on your local network only. Nothing is exposed to the internet, and
no document ever leaves your house.

---

## What's in this folder

| | |
|---|---|
| `Start Print Bridge.bat` | What you double-click. Elevates, checks everything, starts the bridge. |
| `Install Autostart.bat` | Makes it start with Windows, hidden. Run once. |
| `Stop Starting With Windows.bat` | Undoes that, and stops it. |
| `Printer Quality Settings.bat` | Opens the driver settings that control quality and toner. |
| `run_hidden.pyw` | How the auto-start task launches it without a console. |
| `printbridge\` | The bridge itself. Python, no framework. |
| `web\index.html` | The page browsers get. Add more files to `web\` and they're served too. |
| `spool\` | Where a job lands while it's being printed. Emptied as it goes. |
| `simulated-jobs\` | Only used by `--simulate`. |

Inside `printbridge\`:

| | |
|---|---|
| `ipp.py` | The printing protocol itself — binary encode and decode. |
| `model.py` | What a printer looks like to a phone, and the job queue. |
| `server.py` | HTTP front door: IPP for phones, eSCL for scanning, JSON for the web page. |
| `discovery.py` | The Bonjour announcement that makes it appear by itself. |
| `backend.py` | Finds your printers, and picks how a job gets printed. |
| `winprint.py` | The printing itself — pixels onto a printer device context through GDI. |
| `render.py` | PDF to pixels, page placement, and writing PDFs back out. |
| `scan.py` | Drives the scanner through Windows Image Acquisition. |
| `escl.py` | The scanning protocol phones speak. |
| `urf.py` | Decodes the Apple Raster an iPhone sends, back into a PDF. |
| `icons.py` | Draws the printer icon your phone shows. |
| `tray.py` | The notification-area icon and its menu. |

---

## Limits worth knowing

- **PDF, Apple Raster, and images.** That covers iPhone, Android, macOS and
  Windows. The one format deliberately refused is PWG raster, which nothing
  here sends in practice; a job in that format is rejected with a clear message
  rather than printed as garbage.
- **One printer, one job at a time**, which is what the hardware does anyway.
- **The PC has to be awake.** It's doing the rendering. If that becomes annoying,
  the same architecture runs on a Raspberry Pi Zero 2 W that draws about a watt
  and never sleeps.

## How it was checked

The protocol layer is tested against **`ipptool`**, the conformance suite that
ships with CUPS: the full IPP/2.0 test file passes 32 of 32 checks, with
Print-URI and Send-URI correctly reported as unsupported.

Discovery is verified against **Avahi**, a completely separate mDNS
implementation, which resolves both the plain `_ipp._tcp` service Android looks
for and the `_universal._sub._ipp._tcp` AirPrint subtype iOS requires. The
advertised keys were compared side by side against what CUPS publishes for a
shared queue, since that combination is known to satisfy iPhones.

The Apple Raster decoder was checked against **real Apple Raster produced by
CUPS**, not a hand-made sample: a two-page document was rendered to raster,
decoded here, and compared with a reference render of the original at the same
resolution — 99.6% of pixels land within 8/255 of it, and the two are
indistinguishable side by side.

Driverless setup was verified by pointing CUPS' own `lpadmin -m everywhere` at
the bridge — the same auto-configuration Android and macOS perform — which
built a working queue from the advertised attributes alone and printed through
it. Transport was checked with chunked uploads, `Expect: 100-continue`,
connection reuse, and a 6 MB job verified byte-for-byte at the far end.

---

## Credits

Built by **Hafi** — [@hafeee44-lab](https://github.com/hafeee44-lab).

Released under the MIT licence; see `LICENSE`. It leans on
[PDFium](https://pdfium.googlesource.com/pdfium/), through
[pypdfium2](https://github.com/pypdfium2-team/pypdfium2), for rendering, and
[python-zeroconf](https://github.com/python-zeroconf/python-zeroconf) for the
Bonjour announcement.
