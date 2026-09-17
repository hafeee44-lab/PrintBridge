# Contributing

Bug reports are as welcome as patches, especially ones from printers I cannot
test against - the range of Windows print drivers is enormous and most of them
are surprising.

## Reporting a bug

The startup banner says which printing method is live, what the printer is,
and what state the spooler thinks it is in. Please paste it. If a job goes
wrong, run with `--debug-print` and include what the driver answered.

`--test-page` prints one measurable page and nothing else. If that works and
your document does not, say so - it narrows things a lot.

## Working on the code

    python -m pip install -r requirements.txt
    python -m unittest discover -s tests

The tests run anywhere, including Linux and macOS: everything Windows-only is
behind a guard and declines rather than failing. Please keep it that way, and
add a test with any fix - several of the sharper bugs in this project's
history were things a test would have caught in a second.

### House rules

- Standard library only, plus `zeroconf` and `pypdfium2`. A dependency has to
  earn its place; anything needing a compiler does not.
- **Every ctypes call declares `argtypes` and `restype`.** There is a test that
  enforces it. An undeclared call truncates 64-bit handles and produces a bug
  that appears days later on somebody else's machine.
- Windows-only code lives behind `IS_WINDOWS` and returns rather than raises.
- No silent failures. If something did not work, say what and why - a job that
  reports success and prints nothing is worse than an error.

## Layout

    printbridge/     the package
      backend.py     choosing a printer, and the fallback chain
      winprint.py    printing via GDI
      render.py      PDF to pixels, and page placement
      scan.py        scanning via WIA
      escl.py        the scanner protocol phones speak
      server.py      HTTP: IPP, eSCL, the web API
      ipp.py         IPP encode and decode
      urf.py         Apple Raster decoding
      discovery.py   Bonjour/mDNS
      model.py       queues and jobs
      tray.py        the notification area icon
    web/             the browser interface, one file
    tests/           unit tests
    build/           PyInstaller spec for the single .exe
    win7/            the Windows 7 launcher
