# Raspberry Pi voice assistant

Target: Raspberry Pi Zero 2 W (Debian 13), ReSpeaker 2-Mic HAT v1/WM8960, MAX98357A I²S amplifier and speaker. This is a **thin, trusted edge device**, not another agent runtime. Audio processing, wake-word gating, button/LEDs and transport live here; the OpenClaw Gateway owns the agent/session and server STT/TTS services.

## Verified hardware profile

The inventoried Pi reports the `seeed2micvoicec` ALSA capture/playback device and two SPI devices. Its boot setup enables SPI and I²S, selects `dtoverlay=respeaker-2mic-v1_0`, and leaves `i2s-mmap` disabled. `/etc/asound.conf` points to `/etc/voicecard/asound_2mic.conf`. The obsolete Ghostbox service and runtime directories were removed after a verified local backup; the ReSpeaker driver, mixer configuration and overlays were deliberately retained. This inventory is not a claim that the new assistant has been installed.

The confirmed wiring from the legacy bring-up is:

| Function | Pi pin | Device |
| --- | --- | --- |
| 5 V / ground | 2 or 4 / 6 | MAX98357A VIN / GND |
| I²S BCLK / LRCLK / DOUT | GPIO18 pin 12 / GPIO19 pin 35 / GPIO21 pin 40 | MAX98357A BCLK / LRC / DIN |
| Button | GPIO17 pin 11 | ReSpeaker HAT button |
| Status LEDs | SPI0 | Three HAT LEDs |

The MAX98357A receives digital PCM directly: the WM8960 playback mixer is **not** a reliable volume control for that speaker. Apply bounded software volume to the outgoing PCM, then feed the *exact played signal* (with timing) to the acoustic echo canceller's reverse stream. A short silent playback pre-roll may be required to prevent amplifier clicks. Never infer the ALSA card number; identify the card by name at startup and fail visibly if it is missing.

## First milestone: core assistant

- A short button press toggles physical mute. Muted means microphone frames are not sent and wake-word recognition is disabled; the LED shows this unambiguously. A hardware mic power gate would be stronger than software mute, but is not part of this board profile.
- A long press enters volume-adjustment mode; subsequent short presses step through bounded levels, then the mode times out. Exact thresholds and color patterns need on-device usability tests.
- Local “Nova” wake detection opens a bounded listening window. Valid speech/agent activity may extend it; expiration returns to idle. “Stop” immediately cancels local playback and listening. Both words need licensed models and far-field/TV-noise tests before production.
- LEDs distinguish unpaired/offline, idle, listening, processing, speaking, muted and error. Color is advisory, while physical mute state must never be ambiguous.
- OpenClaw remains the single agent core. Inbound device speech is bound to an approved agent and enters the same session/steering path as that persona's Matrix messages. There is no Pi-side agent or separate conversation history.

## Later modes, deliberately separated

This assistant can become both a **communication endpoint** and a **managed device**. Future audio/video calls may be routed between a Matrix/Element caller and this endpoint, or between assistants. An authorized agent may request a time-bounded microphone/camera feed or play media, while the device registry exposes capabilities such as microphone, optional camera, LEDs and speaker. Raw call/relay media is not automatically STT input and must bypass conversation-only wake, gain and suppression where appropriate. This board has no verified camera yet; video is a future capability, not a present feature. Spotify/music and call forwarding are also future modes, not part of the first milestone. See [architecture](docs/architecture.md).

## Bring-up gates

1. Verify named ALSA capture/playback, channel map, GPIO17 and three LEDs; record a local non-sensitive loopback sample. Keep the Ghostbox source repository intact but do not install it.
2. Measure end-to-end speaker-to-mic delay and test local AEC against the actual playout reference. Prefer native WebRTC AudioProcessing with 10 ms frames; avoid a second aggressive AGC competing with the server's speech-level controller.
3. Provision Wi-Fi through a time-limited, button-activated setup hotspot and then enroll the device separately with the Gateway; see the [security and setup design](docs/provisioning.md). No password or bearer token in this repository or process arguments. Require authenticated encryption even on the home LAN.
4. Use the existing OpenClaw agent/session and server STT/TTS pipeline with the **same agent-specific voice profile** as Matrix calling: `think off`, enabled commentary, tool/message policy and other overrides are resolved for the bound agent, not hard-coded for this device. Test greeting, commentary, barge-in, stop, reconnect and queued second utterances. No separate device-side agent loop.
5. Only after these pass, install a least-privilege system service with explicit rollback and rotate the Pi's temporary setup password. Production activation is a separate phase.

The old Voicecore hardware guide is a historical reference in the separate `voicecore` repository, not a runtime dependency.
