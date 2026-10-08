# Raspberry Pi voice assistant

Target: Raspberry Pi Zero 2 W (Debian 13), ReSpeaker 2-Mic HAT v1/WM8960, MAX98357A I²S amplifier and speaker. This is a **thin, trusted edge device**, not another agent runtime. Audio processing, wake-word gating, button/LEDs and transport live here; the OpenClaw Gateway owns the agent/session and server STT/TTS services. Its reusable meeting/realtime engine is already used by Matrix calling.

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

- With `wakeWordEnabled: false` (temporary first-stage setting), one short press toggles **muted ↔ continuous conversation**. The keyword model is not loaded. When explicitly enabled, the original cycle is **muted → Nova wake-word → continuous conversation → muted**; the wake-word conversation has a six-second inactivity timeout. Continuous conversation stays open until muted. The button's mute cannot be remotely undone. It is a software mute, not a hardware microphone power gate.
- The local offline wake detector processes Pi-only 16-kHz PCM; no standby audio is sent to OpenClaw before activation. A bounded 1-second RAM pre-roll and a cheap, slowly learned level gate avoid running the keyword model during quiet standby. An acoustic candidate is **not** itself a wake; it is only checked by the already loaded model. Sustained noise deliberately falls back to continuous keyword checking. The model is an installation artifact, not part of Git. Real Pi pronunciation, latency, CPU and false-wake tests are required before enabling this candidate. “Stop” as a spoken cancel word remains future work.
- An experimental German `Nova` microWakeWord candidate and reproducible training baseline are documented in [the prototype note](docs/nova-microwakeword-prototype.md). A supervised, button-muted Pi trial may select it explicitly; the measured false-wake rate is not acceptable for unattended use.
- LEDs distinguish unpaired, muted, wake-ready, listening, candidate acoustic activity, confirmed speech, processing and speaking. The default is 20% brightness; an authorized agent may set 0–100% brightness and speaker volume separately.
- OpenClaw remains the single agent core. Inbound device speech is bound to an approved agent and enters the same session/steering path as that persona's Matrix messages. There is no Pi-side agent or separate conversation history.

## Later modes, deliberately separated

This assistant can become both a **communication endpoint** and a **managed device**. Future audio/video calls may be routed between a Matrix/Element caller and this endpoint, or between assistants. An authorized agent may request a time-bounded microphone/camera feed or play media, while the device registry exposes capabilities such as microphone, optional camera, LEDs and speaker. Raw call/relay media is not automatically STT input and must bypass conversation-only wake, gain and suppression where appropriate. This board has no verified camera yet; video is a future capability, not a present feature. Spotify/music and call forwarding are also future modes, not part of the first milestone. See [architecture](docs/architecture.md).

## Bring-up gates

1. Verify named ALSA capture/playback, channel map, GPIO17 and three LEDs; collect content-free level metrics and a short speaker probe. Keep the Ghostbox source repository intact but do not install it.
2. Measure end-to-end speaker-to-mic delay and test local AEC against the actual playout reference. Prefer native WebRTC AudioProcessing with 10 ms frames; avoid a second aggressive AGC competing with the server's speech-level controller.
3. Provision Wi-Fi through a time-limited, button-activated setup hotspot and then enroll the device separately with the Gateway; see the [security and setup design](docs/provisioning.md). No password or bearer token in this repository or process arguments. Require authenticated encryption even on the home LAN.
4. Attach a secure device-audio transport to OpenClaw's existing meeting/realtime engine and server STT/TTS pipeline. Resolve the **same agent-specific voice profile** as Matrix calling: `think off`, enabled commentary, tool/message policy and other overrides belong to the bound agent, not this hardware. Test greeting, commentary, barge-in, stop, reconnect and queued second utterances. No separate device-side agent loop.
5. Select an immutable candidate with an explicit rollback for a supervised trial; call it accepted only after real wake/false-wake measurements pass. Before enabling boot autostart, rotate or disable the Pi's temporary setup password. A narrow polkit rule can allow the dedicated runtime identity to request only reboot/poweroff, without general sudo or removing `NoNewPrivileges`.

The old Voicecore hardware guide is a historical reference in the separate `voicecore` repository, not a runtime dependency.
