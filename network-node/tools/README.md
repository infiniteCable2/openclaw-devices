# USB sticker reader

Reads this firmware's permanent setup SSID/password on demand. Requires Python
3.10+ and pyserial; the window also needs Tkinter (included in the usual Windows
Python installer). It uses UART0 at 115200 baud via the board's USB-UART bridge,
as on the CH340 prototype. Native USB CDC/JTAG console profiles are not qualified.

From `network-node`, install the small dependency once:

```powershell
py -3 -m pip install -r tools/requirements.txt
```

Double-click `tools/setup-access.cmd` on Windows, or start the window with:

```powershell
py -3 tools/setup_access.py
```

Choose the USB port and click **Zugangsdaten auslesen**. Close other serial
monitors first. Output can be selected/copied for a sticker. Nothing is saved
automatically. In a terminal (replace the sample port with your device):

```powershell
py -3 tools/setup_access.py --list
py -3 tools/setup_access.py --port COM3
```

On Linux/macOS use `python3` and the relevant `/dev/ttyUSB*`, `/dev/ttyACM*` or
`/dev/cu.*` port. Install Tkinter using the OS package manager if absent, or use
`--port` for terminal output. The tool sends only `netnode setup-access v1` with
a newline and accepts a bounded, versioned JSON reply with a SHA-256 checksum
over `ssid + "\n" + password` to detect serial corruption. This checksum does
not authenticate a malicious device. It closes the port after
success/error and does not deliberately toggle reset/boot lines. Some OS/bridge
drivers can pulse these lines on open; a resulting normal reboot is harmless,
and requests are retried for up to 12 seconds. An unplug/occupied port/older
firmware produces an error instead of flashing or changing configuration.

The reported password is for the hotspot and for the web login immediately
after initial setup or an application factory reset. A separately changed web
password cannot be read out. A factory reset retains the sticker credentials
but removes the OpenClaw identity/session and restores the web login to
`admin` plus the sticker password. A full-chip erase removes the sticker data.

This requires the new firmware AND partition table. The original prototype
firmware does not understand the USB query. Upgrade without erasing NVS so the
existing password migrates unchanged. Test the readout before resetting.

Physical USB serial access is intentionally sufficient to retrieve the hotspot
credentials. Treat the output/clipboard/sticker as a secret; the device never
returns home Wi-Fi or OpenClaw credentials via this protocol.

Protocol tests (no device needed):

```sh
python -m unittest discover -s tests -p test_setup_access.py -v
c++ -std=c++17 -Wall -Wextra -Werror -Itests/fakes -Imain main/provision.cpp tests/provision_test.cpp -o provision-test
./provision-test
```

The C++ test uses the actual persistence implementation with a fault-injectable
NVS model: original-password migration, repeated initialization after default
NVS reset, new-board generation, failed writes/commits and corrupt storage. It
also checks the bounded firmware request parser. These checks do not replace
the real USB/reset/HTTP checks in the hardware qualification document.
