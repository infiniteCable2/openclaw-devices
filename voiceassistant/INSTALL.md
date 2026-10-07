# Voiceassistant installation status and bring-up

The **Pi hardware and local media bridge are validated**, but the assistant is not yet connected to an OpenClaw agent. This is a development procedure, not a production installation. The server-side node-to-Meeting adapter, explicit device-to-agent binding, Gateway admission test and secure Wi-Fi setup portal are still open. Do not enable an unattended service or expose the Gateway for this prototype.

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

The Pi starts muted and unpaired. After successful Gateway admission, a double button press unmutes and opens a bounded listening window; a short single press toggles mute after the double-press interval. Disconnect or revocation returns to muted/unpaired state and clears active media. A live bridge keeps the listening window open for later utterances and barge-in. The runner reconnects with bounded backoff but will not downgrade TLS.

The temporary setup login must be rotated or disabled before an unattended service is enabled. A separate, reviewed deployment step should install only this subtree under a dedicated service account, perform pairing and STT/TTS loopback, and retain a validated rollback.
