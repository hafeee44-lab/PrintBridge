# Security

## What Print Bridge exposes

Print Bridge listens on TCP 631 on every interface and answers IPP, eSCL and a
small web page. That is deliberate: it has to be reachable from phones on the
same network. It is designed for a **trusted local network** and nothing more.

Anyone who can reach the port can print, scan, and read the list of printers.
They cannot browse the PC: the server answers a fixed set of paths and serves
static files only from its own `web/` folder.

There is no TLS. Traffic on the local network is not encrypted, so a document
in flight is readable by anyone who can already see your LAN traffic.

## Do not put it on the internet

Do not port-forward 631, and do not run it on a network you do not control.
Nothing here is written to survive a hostile caller.

On a shared or office network, start it with a code:

    Start Print Bridge.bat --pin 4417

That requires the code on every print, scan and web request.

## Reporting a problem

Open a GitHub issue for anything that is not directly exploitable.

For something sensitive, please use GitHub's **private vulnerability
reporting** on this repository rather than a public issue, so it can be fixed
before it is described.

Please include what you did, what happened, and the Windows and Python
versions. A log from `--debug-print` helps.

## Supported

The latest release only. This is a single-maintainer project.
