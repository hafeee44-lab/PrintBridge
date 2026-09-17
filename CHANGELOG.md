# Changelog

All notable changes to Print Bridge. Dates are when the work landed, not when
it was released.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and versions follow [Semantic Versioning](https://semver.org/).

## [4.0] - 2026-09-17

One codebase for every supported Windows. The separate Windows 7 tree is gone:
its differences were always fallbacks, not a fork, so they now live in the main
files and fire only when the modern path finds nothing.

### Added
- The bridge reports what the **spooler** thinks is going on - paused, offline,
  out of paper, jam, door open, out of toner, "Use Printer Offline" and the
  rest - at startup, before every job, and on the web page.
- **Clear the queue**: a button on the web page, an item in the tray menu, and
  `--clear-queue`. Cancels everything waiting and takes the printer off pause.
- `--test-page` prints one measurable page and exits: a border 10mm in, a 100mm
  square, ticks every 10mm.
- `--debug-print` logs what the driver is told and what it answers.
- Spool housekeeping: files left behind by jobs that never finished are swept
  at startup, and jobs dropped from the history take their files with them.

### Fixed
- `StretchDIBits` returns `GDI_ERROR`, which arrives as `-1`, not `0`. The old
  check let a completely failed page report success - a job would say "done"
  and print nothing.
- `HALFTONE` stretch mode on a printer device context. It is meant for screens
  and makes some drivers produce a blank sheet.
- The DEVMODE claimed colour on monochrome printers and duplex on printers with
  no duplexer. It now asks the driver first and touches as little as possible.
- `job-impressions` reported 1 for every job regardless of page count.

### Changed
- **Repository layout.** The package sits at the repository root instead of
  inside a folder: documentation in `docs/`, the PyInstaller spec in `build/`,
  the Windows 7 launcher in `win7/`, tests in `tests/`.
- The helper scripts now pick their own path for whichever Windows is in front
  of them. `Printer Quality Settings.bat` reads the default printer from the
  registry before asking CIM, and `Stop Starting With Windows.bat` falls back to
  `wmic` where `Get-CimInstance` does not exist - so there is one copy of each
  rather than a Windows 7 duplicate.
- Batch files are stored with CRLF endings, enforced by `.gitattributes`.

## [3.3] - 2026-09-17

### Fixed
- **28 ctypes calls had no `argtypes`.** Undeclared, ctypes marshals a handle as
  a 32-bit int; 64-bit Windows hands out handles above `0x7FFFFFFF` whenever it
  likes. Printing worked until it suddenly did not, with
  `OverflowError: int too long to convert`. A test now enforces the rule.
- The failure message told people to install a PDF engine they already had.

## [3.1] - 2026-09-17

### Added
- **Scanning.** The scanner is shared over eSCL, so iPhones (Files, then Scan
  Documents) and Mopria Scan on Android find it with nothing installed.
- A **Scan** tab in the web page: resolution, colour mode, multi-page, save as
  PDF, print directly.
- Scanned pages carry **Card front** / **Card back** buttons that drop them
  straight into the card composer.

## [3.0] - 2026-09-17

### Added
- **Print Bridge renders PDFs itself**, with PDFium, and sends pages to the
  driver through Windows' own graphics layer. SumatraPDF is no longer needed.
  Exact physical sizing, real duplex-edge control, and reverse page order in
  one job rather than one job per page.
- JPEGs from phones are wrapped in a one-page PDF with the compressed bytes
  passed through untouched.
- A **tray icon** and a **single-file .exe** build.

## [2.6] - 2026-09-11

### Added
- Rebuilt web interface: light and dark, three tabs, live previews.
- **Card sheet**: tile a CNIC, passport photo or business card at exact
  millimetre sizes, with cut marks. A back image produces a second sheet laid
  out mirrored so backs land behind fronts after the flip.

## [2.4] - 2026-09-11

### Fixed
- `sides-supported` was hardcoded to `one-sided`, so no phone ever offered a
  both-sides control. It now asks the driver whether a duplexer exists.

## [2.1] - 2026-09-11

### Fixed
- The bridge shared **Microsoft XPS Document Writer** instead of the printer,
  because it trusted the Windows "default" flag. Real hardware now wins.
- Printer enumeration fell back to a registry scan that only found virtual
  printers. It now calls `EnumPrintersW` first.
- `find_sumatra` only matched an exact filename, so the version-named portable
  download was never found.

## [2.0] - 2026-08-19

First working version: IPP printing, Bonjour discovery, Apple Raster decoding,
manual duplex, and a web page.
