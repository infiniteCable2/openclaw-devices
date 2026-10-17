# Sticker credential and USB verification — 2026-10-18

Working-tree changes on devices base `effc229`, including the board profiles
documented in the earlier build record. No device was flashed or reset and no
Gateway was contacted in this phase. These are software checks, not hardware
acceptance of the new firmware.

Firmware input SHA-256:
`9ba37f5369a652c429d6329e1bf6bdc4beaaa097f17ba1128853a73534f57812`.
This covers sorted relative path, NUL, UTF-8 bytes normalized to LF, NUL for
`main/**`, `boards/**` excluding Markdown, and root `CMakeLists.txt`,
`platformio.ini`, `sdkconfig.defaults` (31 inputs). USB tools/tests/docs are
outside this firmware fingerprint and are included in the source commit.

## Checks

- The actual `provision.cpp` compiled with Zig 0.14.1's host C++ compiler,
  C++17 and `-Wall -Wextra -Werror`, against a fault-injectable NVS model.
  Passed: original-password migration, retention across default-NVS resets,
  existing provision data taking priority, fresh-board generation, failed
  writes/commits, initialization/read errors, corrupt credentials, missing
  credentials on a marked provisioned device, unsupported storage version and
  recovery after a password write interrupted before its version marker.
  Errors leave the output unpublished instead of silently replacing the secret.
- The same host executable checked firmware request framing, CRLF, wrong
  version, oversized lines, embedded NUL and recovery to the next valid request.
- Python 3.12: **6/6** USB/layout tests passed. Coverage includes version/schema,
  checksum corruption, boot noise, fragmented and overlong replies, timeouts,
  disconnected writes and port closure. The layout test checks that both boards
  retain the original NVS/PHY/application ranges and provisioning stays in the
  old gap with sufficient page alignment/capacity.
- Tkinter GUI initialized and closed successfully in a hidden window with a
  synthetic empty port list. CLI help passed. No physical USB query was made.
- Existing shared transport client: **7/7** Node.js contract tests passed.

## Firmware builds

Sequential commands: `pio run -e esp32-4mb --jobs 4`, then
`pio run -e esp32s3 --jobs 4`. PlatformIO Core 6.1.19, espressif32 6.13.0,
ESP-IDF 5.5.3 and Xtensa GCC 14.2.0 (`20251107`), with board-specific locks.
After the final storage-error guard, the ESP32 build was updated incrementally
with the same command; the S3 object was compiled after that source change.

| Profile | Program bytes | App capacity | Static RAM bytes | Result |
| --- | ---: | ---: | ---: | --- |
| `esp32-4mb` | 1,211,197 | 4,063,232 | 38,896 | Passed |
| `esp32s3-16mb` | 1,208,101 | 4,194,304 | 40,080 | Passed |

ESP32 image SHA-256:
`9262cb1baf72c9b98edc95badcc75398692f53c952cf5f3530933f9253da6fbd`.
S3 image SHA-256:
`daf82c066a2cded55486a9ed95d6a6229e7f59abf628560bc084b3213ac69877`.

Both generated binary partition tables passed entry/range and embedded MD5
checks. Their generated SDK configurations selected the intended board layout
and UART0 at 115200. The ESP32 image header also selected DIO / 40 MHz / 4 MB.
Default NVS, PHY and application ranges are unchanged; `provision` occupies the
old 24 KiB gap. Reset still calls the SDK's default-partition erase API, whose
[documented scope is the partition labelled nvs](https://docs.espressif.com/projects/esp-idf/en/v5.5.3/esp32/api-reference/storage/nvs_flash.html#_CPPv415nvs_flash_erasev).

The UART reader uses bounded nonblocking polling in the existing main loop,
not another task/stack. Linker RAM is not peak runtime heap. Both profiles
must select UART0 / 115200 for this USB-UART implementation.

## Remaining hardware acceptance

Upgrade the actual board with matching partition table/application while
preserving default NVS; verify the old password through the USB tool, reboot,
perform authenticated and physical resets, and verify the same hotspot and
password plus restored web login. Confirm the old OpenClaw identity/session is
removed. These checks have not been performed on this revision. The previous
validated firmware and original device backup remain the recovery baseline.
OpenClaw pairing and host plugin/context integration remain separate work.

## Cleanup

Removed task-owned SDK/tool installations, download cache, build trees, host
test executable/debug symbols, full build logs, generated managed components,
SDK configs and Python bytecode after their consumers finished. The previous
validated firmware/original backup were rechecked and preserved; unrelated
shared caches and data were left alone. A small ESP32-only candidate image
bundle and manifest remain locally for the pending physical update. It is
explicitly unvalidated on hardware and does not replace the recovery baseline;
remove this temporary exception after installation/acceptance or abandonment.
Source, pins and concise verification evidence remain in the repository.
