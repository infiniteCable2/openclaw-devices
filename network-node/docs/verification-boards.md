# Board-profile verification — 2026-10-17

Working-tree board-profile changes on devices base `effc229`. This is software
build evidence, not a hardware qualification or a deployed release. No firmware
was flashed and no Gateway was contacted during these checks.

The observed prototype's ROM reported ESP32-D0WD-V3 revision 3.1, 4 MB flash
and a 40 MHz crystal. The USB interface was a CH340. The exact carrier/module
and PSRAM are not established by that identification.

Build commands: `pio run -e esp32-4mb --jobs 4` and
`pio run -e esp32s3 --jobs 4`, run sequentially.
PlatformIO Core 6.1.19, espressif32 6.13.0, ESP-IDF 5.5.3 and Xtensa GCC 14.2.0
(`20251107`). Full compile/link/image/size check passed. All five application
translation units use the shared implementation with warnings treated as
errors; no board-specific upstream component variant was needed.

| Profile | Program bytes | App partition bytes | Static RAM bytes | Result |
| --- | ---: | ---: | ---: | --- |
| `esp32-4mb` | 1,204,137 | 4,063,232 | 39,292 | Passed |
| `esp32s3-16mb` | 1,202,597 | 4,194,304 | 40,856 | Passed |

ESP32 application image SHA-256:
`f8c757e4315f540df6beb36fff93aa85d46af498a997f8b26bec3ba7073f7f1c`.
S3 application image SHA-256:
`16299fa9bb53e9e488709500a8c14c5177023b64ef09d2b71447e87c00fd9d0b`.

Generated ESP32 configuration was checked for target `esp32`, flash `4MB`,
DIO / 40 MHz, the profile's partition CSV and both cJSON limits of 16. The
component manager generated that board's own lock; upstream versions/hashes
match the original S3 dependencies. No PSRAM is required by the profile.
The S3 configuration was also checked for target `esp32s3`, flash `16MB`, its
own partition CSV and both cJSON limits of 16. Firmware source fingerprint
remained unchanged across the two builds. Tracked diff and new-file whitespace
checks passed.

Firmware source fingerprint:
`6ff21cfd12ee1cb9cca0d6d2aee5bc401ba470cad5ae1299259dfa5df7af8d30`.
SHA-256 covers the sorted relative path, NUL, UTF-8 bytes normalized to LF, NUL
for `main/**`, `boards/**` excluding Markdown, and root `CMakeLists.txt`,
`platformio.ini`, `sdkconfig.defaults` (27 files). Documentation and generated
SDK configuration/build output are excluded.

Two real CMake negative configurations passed: selecting `IDF_TARGET=esp32s3`
with `NETWORK_NODE_BOARD=esp32-4mb` fails with the required target; selecting
the not-yet-defined C3 SuperMini profile fails as unsupported. Both stop before
SDK configuration. No C3 compatibility claim is made.

Windows tooling required a short physical package-cache path because a filename
inside the IDF archive exceeded the Windows path limit. A temporary drive alias
shortened tool/build paths; no global long-path, authentication or security
setting was changed. Builds used the normal Windows execution environment.

Linker RAM totals are not peak heap measurements. First boot, actual BOOT-pin
behavior on the carrier, Wi-Fi/AP recovery, authentication/reset, pairing,
TCP/UDP/ping/scan traffic and soak tests still require the
[hardware checklist](qualification.md). Host-side agent/context integration
remains separate. The existing shared host tests were not rerun for this
hardware-configuration change.

Cleanup completed after both builds: removed task-owned tool/SDK installations,
package cache (including failed extraction copies), binaries/build trees, logs,
negative-test directories, managed-component downloads and generated sdkconfigs.
The temporary drive mapping was removed and no build consumers remained.
Source, board locks and this concise record are retained. Existing device
firmware, shared caches, agent data and validated recovery material were not
changed; a fresh software build is supported by the retained source and pins.
