# WLAN profile verification — 2026-10-18

Working-tree changes on devices base `399633342e673853e6eb7566231baa49bc68ac9f`.
This phase changes the device firmware/setup page. It does not flash or reset
a physical board, alter a running Gateway, or exercise a production agent.

## Implemented behavior

- Up to eight individually removable WLAN profiles with per-SSID credentials,
  DNS and hidden-network metadata; one preferred WLAN. Legacy single-network
  settings migrate in memory and persist in the new format on the next save.
- Reboot preserves profiles; the existing default-NVS factory erase removes
  them. Separate sticker provisioning storage and partition layouts are intact.
- The real Wi-Fi manager cycles unsuccessful attempts about every 15 seconds,
  retries the active profile first after loss, and opens the recovery AP after
  30 seconds without an IP. It keeps an acquired fallback until loss/reboot.
- Authenticated, CSRF-protected asynchronous discovery with at most 32 returned
  records, strongest-signal SSID deduplication, unsupported-security labels,
  15-second rate limit and 15-second execution timeout. SSIDs are printable UTF-8
  of at most 32 bytes. Manual entry also permits hidden networks.
- DNS is selected from the active profile; clearing stale custom resolvers uses
  `esp_netif_tcpip_exec`/`dns_setserver` in the pinned SDK's TCP/IP task. The
  higher-level `esp_netif_set_dns_info` rejects zero addresses and cannot clear
  a resolver. Native Gateway reconnect cancellation remains in the main loop.
- HTTP status is redacted; editing a different SSID cannot inherit another
  profile's secret. Serialized settings are rejected before storage if larger
  than the boot reader's bound. The preferred profile retains the old top-level
  fields for a code-only rollback to the preceding firmware.

## Passed software checks

- Actual `core.cpp`, C++17, `-Wall -Wextra -Werror`, Zig 0.14.1 host compiler;
  managed cJSON 1.7.19~2 compiled separately as C with the firmware's nesting
  limits. Original policy/configuration suite plus profile migration, reboot
  serialization, redaction, preferred/deleted/last-profile handling, per-profile
  DNS, hidden flag, duplicate/eight-profile bounds, UTF-8 boundaries and secret
  isolation passed.
- Actual `wifi.cpp` compiled against a small SDK model with the same warning
  settings. Passed preferred/fallback order, current-profile retry, recovery AP
  opening/closing, secure/open authentication threshold, per-profile DNS and
  stale-DNS clearing, connected/offline scans, deduplication, unsupported/hidden
  results, SDK-reported failure, timeout cleanup and rate limiting. A separate
  empty-profile process confirmed immediate setup AP with no station attempt.
  This models SDK events; it is not radio/DHCP or WebSocket hardware acceptance.
- **8/8** Playwright browser tests passed against the actual embedded HTML and
  intercepted synthetic APIs: editing/deletion, manual hidden SSID, pending edit
  inclusion on save, new-SSID password isolation and explicit open selection,
  deleting the final WLAN, freeing a full list without discarding a new draft,
  asynchronous scan/text-only SSID rendering, periodic
  status preserving unsaved fields, and desktop/mobile viewport fit.
- Desktop (1100 px) and mobile (390 px) screenshots visually inspected. No real
  SSIDs, credentials or device addresses are present in fixtures/screenshots.
- Existing shared transport: **7/7** Node.js tests passed. USB/layout: **6/6**
  Python tests passed. Actual provisioning implementation's host tests passed
  reset retention, migration, storage failures and serial framing.

## Remaining hardware acceptance

Flash the matching candidate only in an authorized installation phase while
preserving the current default NVS and provisioning partition. Confirm the
existing WLAN and native identity/session survive upgrade. Test discovery while
the Gateway is connected, a real hidden SSID, multiple saved networks with one
unreachable, per-WLAN DNS, per-profile deletion, reboot retention, and recovery
AP access after deleting the last profile. Measure free/minimum runtime heap.
Factory reset is a separate destructive check requiring explicit authorization;
the paired device was not reset for these software checks.

## Final firmware builds

PlatformIO Core 6.1.19, espressif32 6.13.0, ESP-IDF 5.5.3, Xtensa GCC
14.2.0 (`20251107`), C++17 and the board-specific component locks. Commands:
`pio run -e esp32-4mb --jobs 4`, then `pio run -e esp32s3 --jobs 4`, sequentially.
Final builds used a consistent canonical build-directory path; tool/package
paths were kept short for Windows archive extraction.

| Profile | Program bytes | App capacity | Static RAM bytes | Result |
| --- | ---: | ---: | ---: | --- |
| `esp32-4mb` | 1,246,121 | 4,063,232 | 39,576 | Passed |
| `esp32s3-16mb` | 1,243,529 | 4,194,304 | 41,200 | Passed |

ESP32 image SHA-256: `1e042d4576cfebb9b384d42064e13038751376f422234abc4996384c09f990c8`.

S3 image SHA-256: `70a5d01c426df345bb69b8e3096e92e387e85adede17404b8c0f556c6562c180`.

Both binary partition tables passed range and embedded-MD5 checks. The ESP32
table exactly matches the existing validated device layout; its application
header selects ESP32, DIO / 40 MHz / 4 MB. No partition ranges changed.
Static linker RAM is not a measurement of peak runtime heap.

Firmware input SHA-256: `49deb1e8d5249cf2d4a499f2f115135279c95d637d0e7c82b4b6a3af43780d81` (32 inputs). This covers sorted
relative path, NUL, bytes normalized to LF, NUL for `main/**`, `boards/**`
excluding Markdown, plus root `CMakeLists.txt`, `platformio.ini` and
`sdkconfig.defaults`. Tests/docs/preview are outside this firmware fingerprint.

## Embedded-page regression

PlatformIO did not reliably regenerate the old CMake `configure_file` header
on HTML-only edits. Replaced it with ESP-IDF `EMBED_TXTFILES` and the matching
PlatformIO `board_build.embed_txtfiles` dependency. Final images were checked
for exactly one byte-identical copy of the current UTF-8 HTML plus terminator.
An ESP32 incremental build with only a temporary HTML comment changed the
embedded page and image; restoring the source and rebuilding restored the exact
original image SHA-256. The probe comment is absent from the delivered source
and candidate. No build-directory cleaning was used between these probe steps.


## Cleanup and retained recovery

Removed the task-owned SDKs/compilers, Python environments, download/cache
files, both build trees, host test binaries, full build logs, generated managed
components/SDK configurations and temporary browser captures. Only the updated
synthetic preview and concise verification remain tracked. A small ESP32-only
candidate bundle with checksums is retained locally for the pending physical
installation; it is not a replacement for validated recovery. Remove that
pending-install exception after installation/acceptance or abandonment.

The existing validated firmware/partition/bootloader and recovery records were
checked and preserved. Current device NVS, sticker storage, native identity and
Gateway session were not read back, written or restored during this phase.


## ESP32 USB installation and focused hardware acceptance — 2026-10-18

Subsequently installed the ESP32 application on the previously identified
ESP32-D0WD-V3 / 4 MB board. The source fingerprint and application hash above
were rechecked before flashing. Used esptool 4.11.0, ROM/no RAM stub,
uncompressed application-only write at `0x20000`. Bootloader and partition table
were not written. A fresh protected-region checkpoint (`0x9000`, `0x17000`
bytes) compared byte-for-byte equal BEFORE the first boot; application and
unchanged bootloader/partition MD5 checks passed. No stale state was restored.

Passed on the real board: existing Wi-Fi, native saved-session Gateway reconnect,
unchanged context/mode/permissions/DNS, migration of the existing WLAN into one
redacted profile, an exact HTTP copy of the current UTF-8 portal, unchanged
USB/sticker credentials, and an actual asynchronous WLAN search (five networks).
The node remained/reconnected online with its Gateway after the scan. No
settings save, profile edit, factory reset, agent assignment or target-device
control was performed. Multi-profile failover, hidden-WLAN radio behavior and
factory reset remain hardware qualification items; S3 was cross-built only.

The validated installed recovery now contains this application with the prior
device-verified bootloader/table. The preceding validated application is retained
as a code-only rollback preserving current NVS. The consumed flash candidate/tool environment, obsolete private checkpoint and
before/after status copies were removed after acceptance. The newest validated
installed code and immediately preceding validated rollback were rechecked and
retained; older superseded rollback code was removed. Final LAN and native
Gateway checks remained successful. Recovery remains possible without rewinding
current device or agent state.
