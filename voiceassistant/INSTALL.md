# Voiceassistant installation status and bring-up

The Pi is paired to an OpenClaw agent through the native Gateway node transport and shared Meeting engine. This document describes the next candidate, not proof that its wake-word and device-control changes are deployed. Keep the selected release and its validated rollback until the new candidate passes real-device acceptance. The Wi-Fi setup portal remains future work.

## Local, hardware-free validation

With Python 3.11 or newer in `voiceassistant/`:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

These tests cover controls, cryptographic device identity, node frame shape, bounded audio transport and fail-closed mute behavior. They do **not** prove Gateway admission or end-to-end STT/TTS.

## Pi-local hardware probe

On the Raspberry Pi Zero 2 W, use read-only checks first:

```sh
cat /etc/os-release
aplay -l
arecord -l
ls -l /dev/spidev0.*
```

Expected: named ALSA card `seeed2micvoicec`, `capture`/`playback` endpoints and SPI LEDs. Confirm rather than hard-code the card index. For a fresh Pi, install the distribution packages `python3-alsaaudio`, `python3-cryptography`, `python3-gpiozero`, `python3-spidev`, `python3-websockets`, `libspeexdsp-dev`, `libwebrtc-audio-processing-dev`, `g++` and `pkg-config`. Build and probe locally:

```sh
sh native/build.sh
PYTHONPATH=src python3 -m openclaw_voiceassistant.smoke --library build/libopenclaw-apm.so
PYTHONPATH=src python3 -m openclaw_voiceassistant.smoke_bridge --library build/libopenclaw-apm.so --seconds 1
```

The probes do not retain microphone audio. The second exercises the 16-kHz local AEC path and 24-kHz Meeting transport shape without a server. The delay estimate is currently 40 ms; calibrate it with real simultaneous speaker and mic activity before claiming acoustic echo cancellation quality.

## Device process, after server integration

`device-config.example.json` lists only public endpoint and local file paths. Copy it to a machine-local, untracked config, replace the example endpoint with a certificate-valid `wss://` Gateway name, and protect the state directory. Never put a token or private key in this repo or process arguments. The process uses the native signed node handshake and advertises only `voiceassistant.audio`:

`gatewayConnectHost` is an optional private LAN IP for the TCP connection when
local DNS does not resolve the certificate name to the LAN. TLS still verifies
the hostname in `gatewayUrl`; this does not change system DNS or accept a
self-signed/mismatched certificate. Omit it for a remotely routed device.

If the Gateway requires its shared token for first enrollment, a temporary
`gatewayTokenPath` may point to a private, regular, mode-0600 file. This uses
native `auth.token`, **not** a setup/bootstrap token. Remove that shared
credential after the paired device has received its own `tokenPath` token.

```sh
PYTHONPATH=src python3 -m openclaw_voiceassistant --config /absolute/private/device-config.json
```

The candidate requires a private, absolute `wakeModelDirectory` containing the tested Sherpa-ONNX Nova model files and a locally prepared `keywords.txt`. Install the CPU-only Python runtime in the candidate environment; do not commit or distribute model weights from this repository until their redistribution license is resolved. The Pi starts muted. After Gateway admission, each short press cycles muted → wake-word → continuous → muted. A local Nova detection opens a six-second inactivity window, held by active speech/processing/playout. A remote agent can adjust 0–100% speaker volume and LED brightness, select an unmuted mode, or mute; it cannot override a physical button mute. Disconnect or revocation returns to mute and clears active media.

The optional root-owned [`49-openclaw-voiceassistant-power.rules`](deploy/49-openclaw-voiceassistant-power.rules) authorizes only the dedicated runtime identity for login1 reboot and power-off. Install and verify it separately; do not broaden the service's sudo rights or disable `NoNewPrivileges`. A shutdown may require physical power to restore. Enable boot autostart only after password hardening, model/CPU validation, audio acceptance and a validated rollback.

The temporary setup login must be rotated or disabled before an unattended service is enabled. A separate, reviewed deployment step should install only this subtree under a dedicated service account, perform pairing and STT/TTS loopback, and retain a validated rollback.
