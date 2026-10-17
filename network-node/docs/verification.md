# Software verification — 2026-10-17

This records the original S3 implementation/layout published in `effc229`.
Later [board-profile builds](verification-boards.md) are recorded separately;
the input fingerprint below describes that original layout before files moved
into board directories.

Software verified against devices base commit
`2b37410d29f766f80757cfdc9ecdd429b6d08462` before publication. No device was
flashed, Gateway contacted or agent state changed.

- ESP32-S3 cross-build **passed** with PlatformIO Core 6.1.19,
  espressif32 6.13.0, ESP-IDF 5.5.3 and the checked-in managed-component lock.
  Final command: `pio run -e esp32s3 --jobs 4`. The final image/size step passed
  after full compilation and a tooling-only packaging retry.
  The SDK was confirmed to select 16 MB flash and JSON recursion limits of 16.
- Program size: **1,192,557 bytes** of the 4 MiB application partition.
  Static RAM: **39,952 bytes** of 320 KiB. These are linker measurements, not
  runtime peak heap, Wi-Fi stability or throughput qualification.
- Portable C++ policy/configuration tests **passed**, compiled with warnings
  treated as errors and the actual resolved Espressif cJSON source. Coverage
  includes strict target parsing, CIDR/port/protocol separation, MAC pins,
  default deny, malformed settings, credential redaction and deep-JSON rejection.
- Shared protocol client: **7/7 Node.js tests passed** (about 0.18 s). They cover
  context isolation/reassignment/revocation, trusted session propagation,
  chunking, partial acknowledgements, abort cleanup, UDP limits, malformed
  replies and partial scan reporting. These are host contract tests, not a
  firmware/Gateway end-to-end test.
- Setup page inspected in a browser using a synthetic localhost fixture.
  Adding an ICMP rule selected ports 0/0 correctly. The retained screenshot uses
  fictional SSID/Gateway/context data and documentation IP addresses. The
  temporary preview tab/server were closed.
- Tracked diff and new text-file whitespace checks passed.

Windows qualification needed normal execution outside the sandbox because the
target compiler's launcher failed with access error 5 inside it. Esptool's
Python dependencies were installed in the task-only venv using that same normal
execution context after a mixed-context file-permission failure. No global
authentication/security settings or credential permissions were changed.

Firmware input fingerprint:
`e9f676d2cf2374ea4cff49fb4c9da40cd53433a5b14f8b636e6e50e88d702dda`.
This hashes the sorted relative filenames, NUL, file bytes, NUL for `main/**`
and the root CMake, PlatformIO, partition, SDK-default and dependency-lock files
(17 inputs). Built application image SHA-256:
`42db956d54787fdbb9de0171246c332248329e0ff0add97da2ea9c61fbd8d774`.
The image is software-build evidence, not a validated hardware recovery image.

Outstanding acceptance: the [hardware checklist](qualification.md), including
real HTTP authentication/password/reset behavior, Wi-Fi recovery, native
pairing/revocation, actual TCP/TLS/UDP/ICMP traffic and memory/soak measurements.
Host-side enforcement of per-agent context grants at the common node-invoke
boundary remains a separate integration step; the supplied protocol client is
not an installed Gateway plugin.

Cleanup completed: removed the task-owned firmware build, disposable toolchain
and Python installations, test binaries/logs/fixtures, managed-component
downloads and generated SDK configuration after their consumers finished.
Source, dependency pins, this record and the synthetic UI preview are retained.
No pre-existing release, rollback, shared package/model cache or agent data was
removed. No deployed state changed; source and pins support a fresh build and
existing validated recovery material remains untouched.
