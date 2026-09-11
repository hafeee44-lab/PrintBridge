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
- installs the one library it needs for network announcements
- offers to install **SumatraPDF**, which prints a PDF with no dialog and, more
  importantly, **with rescaling switched off** — that's what makes a page come
  out at its exact physical size
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

The M1132 can't turn the paper over by itself, so the web page walks you
through it: set **Both sides** to *On*, print, and it does the front of every
sheet, then stops and tells you to turn the stack over and put it back. One
tap does the rest.

If the second side comes out in the wrong order, set **Second pass** to
*Reverse order*. Printers stack paper differently and there's no way to know
yours without trying — the reverse option sends the back sides one page at a
time so the running order is certain rather than left to the driver.

### 4. If a device won't find it — use the web page

Open `http://<the address above>` in any browser. Pick files, choose settings,
print. Add it to your home screen and it behaves like an app. It handles PDFs
and images, several at a time, and it's a useful sanity check when discovery is
being difficult.

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
| Every job fails with *no PDF handler available* | SumatraPDF is missing and nothing on the PC is registered to print a PDF. Drop `SumatraPDF.exe` (the portable build is fine) into this folder and restart. |
| Prints, but the size is wrong | SumatraPDF isn't installed, so the job fell back to your default PDF app, which rescales. Install it and restart the bridge. |
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
| `server.py` | HTTP front door: IPP for phones, JSON for the web page. |
| `discovery.py` | The Bonjour announcement that makes it appear by itself. |
| `backend.py` | Finds your printers and hands files to SumatraPDF. |
| `urf.py` | Decodes the Apple Raster an iPhone sends, back into a PDF. |
| `icons.py` | Draws the printer icon your phone shows. |

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
[SumatraPDF](https://www.sumatrapdfreader.org/) for silent, unscaled printing
and [python-zeroconf](https://github.com/python-zeroconf/python-zeroconf) for
the Bonjour announcement.
