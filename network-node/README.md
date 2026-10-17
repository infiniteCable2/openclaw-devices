# ESP32 network node

Lightweight, device-side network access for OpenClaw. Plugins, credentials for
target devices, protocol interpretation, agent authorization and scan planning
stay on the OpenClaw host. This firmware opens TCP/UDP sockets and performs
bounded ICMP ping and TCP connect probes in the node's network.

[Setup page preview](docs/portal-preview.jpg) uses synthetic data from a local
browser fixture; it is not a screenshot of a deployed device.

The initial target is **ESP32-S3, 16 MB flash** (for example an S3 N16R8 board).
The firmware does not require PSRAM. Other ESP32 boards need their own build
configuration and hardware qualification; S3 Wi-Fi is 2.4 GHz.

## What is implemented

- Native Ed25519 identity, signed challenge, pairing and device-token reconnect,
  using the pinned upstream `espressif/esp-openclaw-node` component.
- TLS-only Gateway enrollment, public CA bundle or a custom PEM trust anchor.
- WPA2 setup hotspot when no SSID is configured, or after 30 seconds without a
  station IP. It closes after station connectivity returns; Gateway failure
  alone does not open the hotspot. Station reconnects continue during setup.
- Password-protected, self-contained HTTP setup page on the AP and station LAN.
  No CDN, cloud provisioning service or external JavaScript.
- Wi-Fi, context ID, Gateway URL/setup code, CA, allowlist/admin mode, separate
  ping/scan switches, password change, browser time synchronization and factory
  reset. Configuration changes save to NVS and reboot.
- Four simultaneous transport handles, 2048-byte TCP chunks, 1200-byte UDP
  datagrams, idle/absolute expiry and session-bound handles.
- At most one asynchronous probe job with 32 explicit targets. No shell,
  plugin runtime, local model or target-device TLS termination.
- Shared, dependency-free Node.js protocol client in `client/transport.mjs`.

**Integration status:** this adds firmware and its reusable protocol client,
not a deployed OpenClaw plugin. A host integration must supply native
`node.invoke`, trusted session identity and live per-agent context grants.
`local` remains the host's default network context; several node contexts can
be granted simultaneously. The firmware does not grant an agent access merely
because the node is paired. See [the wire contract](docs/protocol.md).

## Build and flash

Use ESP-IDF **5.5.x** (`idf.py set-target esp32s3`, then `idf.py build`), or
PlatformIO Core 6.1.19 with the checked-in platform pin:

```sh
cd network-node
pio run -e esp32s3
# Select the actual board's serial port; this command changes that device.
pio run -e esp32s3 -t upload --upload-port <serial-port>
pio device monitor --port <serial-port> --baud 115200
```

The firmware includes its HTML directly and has no filesystem image. Build
artifacts and managed-component downloads are not source. The dependency lock
records the resolved component versions/hashes. Do not flash or contact an
existing Gateway as part of a build check.

## First setup

1. Open the USB serial monitor at 115200 baud for the first boot. Record the
   unique setup password shown once. There is no shared factory password.
2. Join `OpenClaw-Setup-<device suffix>` with that password, then open
   **http://192.168.4.1**. Sign in as **admin** using the same initial password.
   This is a setup AP, not a DNS-hijacking captive portal.
3. Enter the Wi-Fi SSID/password. Supply a `wss://` Gateway URL and its native
   base64url setup code. The URL inside the code must match exactly. Use a
   public certificate or paste the CA that signed the Gateway's certificate.
   Do not disable certificate checks to connect a private Gateway.
4. Pick a context such as `node1`. Leave **allowlist** selected and add only the
   desired targets, transports and ports. An empty allowlist denies all targets.
   Ping needs the separate ping switch and an ICMP rule (port 0); a scan needs
   the scan switch and a TCP rule for each probed target/port.
5. Save and reconnect to the station IP reported by your router. Approve the
   device and its declared command surface in OpenClaw, then assign context
   grants in the host integration. Pairing and agent grants are separate.
6. Change the web password if desired. This does not change the AP password.
   On a later Wi-Fi outage, the same AP password is used. Blank Wi-Fi passwords
   preserve the existing credential unless **open Wi-Fi / clear password** is
   explicitly selected.

Certificate validation needs a sensible device clock. The firmware uses SNTP
(`pool.ntp.org`). For an isolated LAN, set the clock from the authenticated web
page. An unavailable clock must not cause insecure TLS fallback.

Gateway bootstrap credentials remain only while enrollment is pending; the
native component persists the final device token. A terminal auth rejection
pauses reconnect until local reconfiguration/reboot. A pending pairing request
can retry. The node never switches to a shared credential after device-token
rejection, and a different Gateway URL cannot reuse an old saved session.

## Web administration and recovery

HTTP Basic authentication protects both the page and its APIs. Password
verifiers use per-device random salt and PBKDF2-HMAC-SHA256 (20,000 iterations).
Mutations additionally require the page's boot-local CSRF token; no CORS is
enabled. Status responses never contain Wi-Fi passwords, setup codes, private
keys or device tokens. A small login backoff and bounded HTTP bodies/sockets
limit work on the ESP32.

The management page intentionally uses **HTTP**, as requested. Basic auth does
not encrypt LAN traffic; use the trusted LAN or the WPA2 setup AP. TLS protects
the separate OpenClaw connection. NVS/flash encryption and secure boot are not
enabled automatically because provisioning their keys/eFuses is board-specific.

Factory reset requires the current password and typing `RESET`. Alternatively,
hold **BOOT / GPIO0 for 10 seconds after the application has booted**. Holding
BOOT while powering on may enter the ROM downloader instead. Reset stops the
native client and network work before erasing the firmware's NVS partition:
Wi-Fi, rules, web/AP credentials, Ed25519 seed and saved Gateway session.
The application remains installed, generates fresh credentials and presents
setup again. Old Gateway records/grants must be revoked separately; resetting
a board does not mutate the Gateway or any agent histories.

## Network limits

This is a TCP/UDP socket forwarder, not a transparent layer-2 bridge or full IP
router. The first transport uses bounded native Node RPCs over the existing
WebSocket, so it requires no new public tunnel endpoint. It favors control
traffic over bulk transfer. A future streaming data channel must preserve the
same context, authority, flow-control and lifetime rules.

Targets are explicit canonical IPv4 literals. The host handles DNS and protocol
interpretation. Loopback, link-local, invalid targets, the board's own station
address and the reserved setup subnet `192.168.4.0/24` are blocked even in
admin mode. There is no fallback to another node or to the host's local network.
MAC pins require an exact /32 target on the station's own subnet; missing ARP
entries fail closed while requesting ARP resolution. Retry only within the
host's normal deadline. ARP/MAC is a local consistency check, not cryptographic
device authentication. Pins are rechecked before subsequent I/O.

UDP v1 uses a connected socket per target: unicast request/reply is supported.
Sending explicitly authorized broadcast/multicast packets is possible, but
receiving discovery replies from different peer addresses is not yet supported.
Do not advertise transparent mDNS/SSDP discovery. ICMP ping verifies the source,
ID, sequence and random payload. A missing reply is `no_confirmation`, never
proof that a device is offline. TCP scans are explicit connect probes; there is
no SYN scanner, automatic subnet expansion, fingerprint database or raw packet
injection surface.

## Checks

```sh
node --test tests/transport.test.mjs
# Portable C++ policy/configuration test, using the managed cJSON source:
c++ -std=c++17 -Wall -Wextra -Werror -DCJSON_NESTING_LIMIT=16 -DCJSON_CIRCULAR_LIMIT=16 -I main \
  -I managed_components/espressif__cjson/cJSON \
  main/core.cpp tests/core_test.cpp managed_components/espressif__cjson/cJSON/cJSON.c \
  -o <temporary-test-path>
<temporary-test-path>
```

Run the hardware checklist in [qualification.md](docs/qualification.md) before
claiming an operational node. Host tests and a successful cross-build do not
prove Wi-Fi behavior, firmware memory headroom, native pairing or real traffic.
Remove task-owned build, test and staging output after its consumer finishes.

## Dependencies

- [esp-openclaw-node 1.2.0](https://components.espressif.com/components/espressif/esp-openclaw-node/versions/1.2.0): Apache-2.0, native Node protocol/identity owner.
- Its pinned dependencies are Espressif WebSocket client 1.8.0 (Apache-2.0),
  cJSON 1.7.19~2 (MIT) and libsodium 1.0.22~1 (ISC).
- ESP-IDF 5.5.x / PlatformIO espressif32 6.13.0 supplies Wi-Fi, lwIP, NVS,
  Mbed TLS and the HTTP server. No upstream source is copied into this repo.
