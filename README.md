# Print Bridge

Turn a Windows PC with a USB-connected printer into a wireless network printer.
Print Bridge accepts print jobs from iPhone, iPad, Android, macOS, Windows, and
other IPP-capable clients, then hands them to the printer driver already
installed on the PC.

It is designed for host-based printers that cannot understand PCL or
PostScript on their own. The computer does the rendering; phones and laptops
only need to send a normal network print job.

```text
Phone, tablet, or laptop
					|
					| Wi-Fi: IPP + Bonjour/mDNS
					v
		 Windows PC  ------- USB -------  Host-based printer
		 Print Bridge             Windows printer driver
```

## What it provides

- Standard IPP printing over the local network.
- Bonjour/mDNS discovery so supported devices can find the printer without
	manual setup.
- A browser-based print page for uploading PDFs and images from any device.
- Apple Raster decoding for iPhone and iPad print jobs.
- PDF handoff to the installed Windows printer driver.
- Manual duplex printing with configurable second-pass ordering.
- Sharing of the default printer, selected printers, or every installed printer.
- Optional PIN protection, logging, simulation mode, and per-job size limits.
- Windows startup support through a scheduled task.
- A separate Windows 7 build with PowerShell 2.0-compatible fallbacks.

## Why this approach works

Many inexpensive USB printers are host-based: they rely on the operating
system's driver to rasterize every page. A simple USB print-server adapter can
forward bytes, but it cannot create the printer-specific raster stream those
printers need.

Print Bridge keeps the existing Windows driver in the path. A device sends a
job over Wi-Fi using IPP, Print Bridge receives and normalizes it, and Windows
prints it through the same driver that works when printing locally.

## Requirements

- A Windows PC on the same local network as the client devices.
- A USB printer installed and working in Windows.
- The printer's Windows driver installed on that PC.
- Python installed and available to the launcher.
- Administrator access for the first-run setup and firewall configuration.
- The `zeroconf` Python package for Bonjour/mDNS discovery.
- SumatraPDF for silent PDF printing without unwanted scaling.

The normal build is intended for current supported Windows versions. The
`PrintBridge-Win7` build targets Windows 7 and uses Python 3.8.10, the last
Python version supported by that operating system. Windows 7 has been out of
support since January 2020; use that build only on a trusted private network.

## Quick start

1. Install the printer and confirm that it prints locally from Windows.
2. Open the `PrintBridge` directory.
3. Double-click `Start Print Bridge.bat` and allow the requested administrator
	 access.
4. Complete the one-time Python, dependency, helper, and firewall setup.
5. Leave the console window open while the bridge is running.
6. Print from a phone or laptop, or open the displayed web address in a browser.

The launcher reports the shared printer, IPP address, discovery status, and web
address when startup is complete. On iPhone or iPad, open Share > Print. On
Android, use the system print service or Mopria Print Service. macOS can add it
from System Settings > Printers & Scanners.

The default service uses TCP port `631` for IPP and the web interface, and UDP
port `5353` for Bonjour/mDNS discovery. If port `631` is unavailable, the
launcher can move to the next available port; use the address printed by the
launcher.

## Browser printing

The built-in web interface is useful when automatic discovery is unavailable or
when printing from a device without a native IPP workflow. Open the reported
address, select one or more PDF or image files, choose the available options,
and submit the job. The page can also guide a manual two-sided print workflow
for printers without automatic duplex hardware.

## Command-line options

Arguments can be appended to `Start Print Bridge.bat` or added to the launcher
permanently.

| Option | Purpose |
| --- | --- |
| `--all-printers` | Share every installed printer. |
| `--printer "NAME"` | Share a specific printer; repeat for multiple printers. |
| `--name "Study printer"` | Set the name displayed to client devices. |
| `--location "Office"` | Publish a location beside the printer name. |
| `--port 8080` | Use a different IPP and web port. |
| `--pin 1234` | Require a PIN before accepting a print job. |
| `--brand Generic` | Publish a neutral manufacturer name to avoid vendor-plugin conflicts. |
| `--log-file PATH` | Append service output to a log file. |
| `--max-mb 100` | Set the maximum accepted size for one print job. |
| `--simulate` | Save jobs under `simulated-jobs/` without printing. |
| `--no-discovery` | Disable Bonjour/mDNS while keeping IPP and the web page available. |
| `--list` | List installed printers and exit. |

Example:

```bat
Start Print Bridge.bat --printer "HP LaserJet Professional M1132 MFP" --pin 4417
```

## Start with Windows

Run `Install Autostart.bat` once to create a scheduled task that starts the
bridge at logon without leaving a console window open. Run
`Stop Starting With Windows.bat` to remove that behavior.

## Windows 7 edition

The `PrintBridge-Win7` directory contains the same bridge implementation with
setup scripts adapted for Windows 7:

- Python 3.8.10 instead of a newer Python release.
- No dependency on `winget`.
- PowerShell 2.0-compatible printer discovery fallbacks.
- Windows 7-compatible firewall, networking, and scheduled-task commands.

Read [Windows 7 notes](PrintBridge-Win7/Windows%207%20notes.md) before setup.
Windows 7 may be unable to download installers because modern websites require
TLS 1.2; the notes explain how to place the installers in the local `setup`
directory instead.

## Troubleshooting

### The printer does not appear on a phone

Confirm that both devices are on the same local network and that the bridge
reports Bonjour as advertised. Check that Windows Firewall allows TCP `631` and
UDP `5353`. If discovery still fails, open the displayed web address directly
or start with `--no-discovery` and use the browser interface.

### The wrong printer is selected

List installed printers with `--list`, then select the intended one explicitly:

```bat
Start Print Bridge.bat --printer "Printer name"
```

Avoid selecting a virtual printer such as a PDF or XPS writer unless that is
intentional.

### A page is scaled incorrectly

Use the supplied SumatraPDF helper and check the printer's Windows driver
settings. Print a test page locally first, then compare it with a browser job.
The bridge passes the job through the Windows driver; it cannot correct a bad
driver configuration or a printer-specific media setting.

### Bonjour is unavailable

Another Bonjour service may already be using UDP port `5353`. Stop the
conflicting service or use `--no-discovery` and connect through the IPP or web
address shown at startup.

## Project layout

```text
PrintBridge/
	printbridge/       Python IPP server, discovery, backend, and raster handling
	web/               Browser print interface
	*.bat              Windows setup, startup, and maintenance scripts
	requirements.txt   Python dependency list

PrintBridge-Win7/    Windows 7-compatible variant
PrintBridge-README.md
```

The main implementation is intentionally dependency-light. `zeroconf` is used
for network discovery; Windows and the installed printer driver handle the
platform-specific printing work.

## Development

Install the dependency from the relevant project directory:

```powershell
python -m pip install -r requirements.txt
```

Run the module directly for local testing:

```powershell
python -m printbridge --simulate --no-discovery
```

Simulation mode writes received jobs to `simulated-jobs/` and is useful for
testing the network and web workflow without sending paper through the printer.

## Security and network scope

Print Bridge is intended for a trusted private LAN. The service opens a print
endpoint and, by default, does not provide user accounts or encryption. Use
the PIN option when appropriate, keep Windows Firewall scoped to the local
network, and never expose the service directly to the public internet.

## License

Print Bridge is released under the [MIT License](PrintBridge/LICENSE). The
Windows 7 variant includes the same project license in its directory.

## Detailed documentation

The original device-specific walkthrough and additional operational notes are
available in [PrintBridge-README.md](PrintBridge-README.md). The variant
readmes contain launcher-specific instructions for [current Windows](PrintBridge/README.md)
and [Windows 7](PrintBridge-Win7/README.md).
