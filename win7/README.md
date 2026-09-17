# Windows 7 notes

Everything in `printbridge\` is the same code as the main build. What changes
is the scaffolding around it, because Windows 7 predates the tools the normal
scripts lean on.

## Installing Python and SumatraPDF

`Start Print Bridge.bat` installs both silently, the same way the Windows 10
version does — it just can't use `winget`, which doesn't exist here. It runs
`python-3.8.10 /quiet InstallAllUsers=1 PrependPath=1` and `SumatraPDF -s`, and
finds the new Python by path afterwards, since this window's PATH is already
stale by then.

3.8.10 is deliberate: it is the last release that installs on Windows 7, and
3.9 onward refuse to run here. The bridge's own code is 3.8-clean, so nothing
else is needed. SumatraPDF 3.6.1 still supports Windows 7.

### If the download fails

It might. Windows 7 talks TLS 1.0 out of the box, and both sites are TLS 1.2
only, so a PC that never got the relevant updates can't reach them — the script
tries `certutil`, then `bitsadmin`, then .NET, and any of the three may come
back empty. That is a Windows 7 problem, not a Print Bridge one.

When that happens, download the two files on any other PC:

- <https://www.python.org/downloads/release/python-3810/> — *Windows installer
  (64-bit)*, or the plain one for a 32-bit PC
- <https://www.sumatrapdfreader.org/download-free-pdf-viewer>

Make a folder called `setup` next to `Start Print Bridge.bat`, drop both `.exe`
files in as they are, and run the script again. A file in `setup\` always wins
over downloading, so it installs both without touching the network.

Once Python is on, `pip` can fetch the one library it needs even if the rest of
Windows still can't download anything — Python ships its own TLS stack and
doesn't ask the OS.

## What the scripts do differently

Only two scripts live in this folder. Both run the package from the repository
root one level up, so keep the folder where it is.

| | |
|---|---|
| `Start Print Bridge.bat` | Points you at the two downloads instead of running `winget`, and prints the Python version it found. |
| `Install Autostart.bat` | Finds this PC's address with `ipconfig` instead of `Get-NetIPAddress`, which is Windows 8 and later. |

`Printer Quality Settings.bat` and `Stop Starting With Windows.bat` in the root
folder already handle Windows 7 themselves — the first reads the default printer
from the registry before trying `Get-CimInstance`, and the second falls back to
`wmic` — so there is no separate copy of either here.

## What the bridge does differently

`backend.py` grew two fallbacks, both silent when they aren't needed:

- **Listing printers.** The normal query ends in `ConvertTo-Json`, which does
  not exist in PowerShell 2.0 — so on a stock Windows 7 the whole query fails,
  taking the `Get-WmiObject` fallback with it. There is now a plain-text WMI
  query underneath that works on PowerShell 2.0, so the *default* printer is
  still identified correctly rather than guessed from the registry.
- **The Public-network warning.** `Get-NetConnectionProfile` is Windows 8 and
  later, so the warning that catches the most common "my phone can't see it"
  failure never fired here. It now asks the firewall instead, with
  `netsh advfirewall show currentprofile`.

If you have Windows Management Framework 5.1 installed on this PC, neither
fallback is used — the normal path works.

## Things Windows 7 gets for free

No built-in mDNS responder, so nothing argues with the bridge over the
`.local` name the way Windows 10 does. If iTunes is installed, though, its
Bonjour Service holds port 5353 — stop that service, or run with
`--no-discovery` and use the web page.

## Worth saying once

Windows 7 has been out of support since January 2020, and this PC will be
sitting on your network accepting print jobs. It's fine behind a home router;
don't put it anywhere else.
