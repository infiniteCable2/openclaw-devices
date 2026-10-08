# Voiceassistant architecture: native-core boundary

## Responsibility split

```text
ReSpeaker microphones -> Pi capture -> AEC/NS + wake/stop/mute -> authenticated media transport
                                                            |
                                                            v
Gateway meeting/realtime engine -> existing STT -> OpenClaw agent/session -> existing TTS
                                                            |
                                                            v
Pi playout/volume -> speaker; the same played PCM + timing -> AEC reverse stream
```

The Pi is a **trusted media source**, but its own claims (speech probability, VAD, noise estimate, gain and device health) remain hints. Gateway policy, agent binding and authorization are server-owned. The server speech-focus/AGC2 path should still see unmodified level telemetry where possible; do not run an independently aggressive Pi AGC that erases its evidence. AEC and modest noise suppression are local because the Pi has the real loudspeaker reference and acoustic timing. Raw/relay/recording modes must bypass assistant-specific wake and speech processing by explicit mode, not by accidental reuse of the conversation input path.

## Existing OpenClaw seam and the gap

The reusable speech pipeline **already exists**. Matrix RTC calls `prepareMeetingAgentRealtimeEngine` and `startMeetingAgentRealtimeEngine` through the public `openclaw/plugin-sdk/meeting-runtime` surface. The engine accepts a `MeetingRealtimeAudioTransport` and already handles our configured transcription provider, server TTS/readiness, greeting, waiting audio, commentary, barge-in and common agent consultation/steering. A `createNodeMeetingRealtimeAudioTransport` implementation also exists for paired OpenClaw nodes, although its command/polling shape and full node-host runtime may not be the best fit for a small always-on Pi. The missing piece is a secure **device media transport/admission adapter**, not another STT, TTS or agent loop. This adapter should be reusable by later voiceassistant models rather than Pi-specific.

Preferred work: evaluate the existing node audio transport first with a narrowly declared non-shell media capability. If it proves too heavy or too high-latency on the Pi, add a small authenticated transport implementation behind the same `MeetingRealtimeAudioTransport` contract. Reuse the existing engine, provider configuration, GPU readiness flow and session/agent steering. Implement media backpressure, bounded queues, output acknowledgements/cancel, idempotent reconnect and per-turn ordering at that transport boundary. A device-bound session must not silently fall back to another persona.

The **bound agent's** voice conversation profile must be resolved with the same effective values as Matrix RTC. For Steffen, that currently means `think off` for calls, commentary and the allowed message/tool surface. Today Matrix's profile resolver lives in its own RTC adapter, so extract or reuse its configuration semantics rather than blindly copying constants. This is not a gateway-wide or device-type default; a later Bodo, Astrid or André device receives its own agent's configured profile.

OpenClaw's separate native Talk `stt-tts` relay has its own transport restrictions, but those do **not** block this meeting-engine path. Do not add a Talk relay merely to connect the Pi. A Talk client with on-device STT/TTS would bypass our proven server providers and burden a 416 MiB Pi. Do not introduce an unauthenticated custom WebSocket, a second conversation scheduler or a global bearer token as a shortcut.

## One endpoint, two roles

The assistant is an OpenClaw **communication endpoint** and a **managed device**. These are distinct grants, even if they refer to the same physical identity:

| Mode | Media handling | Authority |
| --- | --- | --- |
| Assistant conversation | Local wake/AEC, server STT, common agent loop, server TTS | Device may address its bound agent; that agent's normal tools apply |
| Matrix/Element or device-to-device call | Negotiated two-way audio, later optional video; no automatic STT/agent injection | Participants and destination must authorize connection |
| Agent-requested live listen/view | Bounded media lease with visible indicator; optional file handoff to user | Explicit device capability and recipient grants; no covert indefinite stream |
| Music/media playback | Playback-only route with volume and interruption policy | Separate media permission; future Spotify account handling is server-side |
| Device control/telemetry | Button/mute, volume, LED, microphone health, optional camera status | Device registry capability and agent/site binding |

Media transport should be reusable across these modes, but their permissions and processing graphs must not collapse into one. For example, forwarding a sound file or live call must preserve the requested media and should not pass through conversation STT, wake gating or speech AGC. A later camera is optional hardware; the current Pi inventory proves microphones, speaker, button and LEDs only. A call to the device is not automatically a call to its bound agent. The device can later act as a Matrix endpoint, with agent participation added only when explicitly requested.

## Pairing and security proposal

Reuse OpenClaw's signed device identity/pairing contract if a thin client can implement the required subset. An administrator approves the device identity and separately binds it to an allowed site, agent and narrow media capability. The device should not receive arbitrary shell or device-control commands. Store its private key in root-owned or service-owned local state, never in Git; expose a one-time pairing code/QR only for enrollment. Support revocation, certificate/key rotation, clock skew, reconnect and explicit unpaired status. The exact Gateway method and permission scope must be verified in source and with a nonproduction handshake before committing to wire format. [Wi-Fi provisioning and encrypted transport](provisioning.md) are separate layers.

Every live listen, camera, raw-media relay or recording requires an explicit grant with recipient, purpose and expiry. An active LED/status signal must survive network interruption and reconnect. Avoid recording by default. The physical mute applies to all microphone routes, including calls and agent-requested capture; only an explicit local unmute can clear it.

## Local acoustic processing

Capture and playout use bounded PCM frame queues and monotonic timestamps. WebRTC AudioProcessing receives 10 ms capture and *actual played* reverse frames; compensate measured I²S/ALSA buffering delay. Avoid hidden fallback to an RMS-only pseudo-AEC when native AEC fails: show an error and choose a deliberate safe degraded mode, such as push-to-talk/no simultaneous playout, only if configured. During playback, far-end echo must not count as local speech or barge-in. A true new utterance can cancel playout immediately; its transcript and any earlier unfinished instruction still enter the common OpenClaw steering path. No transcript may be discarded just because another arrives while tools/TTS run.

Use local speech probability/VAD, input peak/RMS and noise-floor measurements as bounded, versioned metadata with timestamps. These are useful for endpointing and diagnostics, not proof of speech and not a second automatic gain controller. Evaluate AEC, level, latency and false wake/stop on real loudspeaker, TV, car/road-noise and quiet-room recordings. Keep a raw-input capture mode for controlled diagnostics with explicit retention and consent.

The 2-Mic HAT exposes two WM8960 capture channels, but has no verified onboard far-field DSP. The current assistant requests a mono ALSA stream; do not assume the second microphone gives beamforming automatically. Compare each channel and the actual mono mix with explicitly marked speech and quiet windows before selecting a channel, altering fixed analog capture gain, or adding adaptive processing. The server speech-focus path remains the only automatic gain owner. Digital zero pre-roll and a short fade at I²S playout start are a click-reduction candidate; they need an audible MAX98357A test and must not weaken immediate output clearing for barge-in. Waiting audio is owned by the shared Meeting engine, not synthesized independently on the Pi.

## Controls and observability

Button and LED state are local and work offline. With wake-word disabled, one short press toggles muted ↔ continuous conversation and no keyword model is loaded. When explicitly enabled, one short press cycles muted → Nova wake-word → continuous conversation → muted. Wake-word mode opens a six-second inactivity window after detection; active speech, processing and playout hold it open. The physical button mute cannot be remotely cleared. Suggested states: blue wake-ready, green listening, a separate acoustic-candidate color, amber processing, cyan speaking, solid red muted, pulsing red error/unpaired. Colors/patterns are provisional until checked against the physical three-LED HAT; status must also be queryable without relying on color. Default LED brightness is 20% of the hardware maximum. The bound agent can set LED brightness and bounded software PCM speaker volume from 0–100%, switch modes within the mute rule, and request explicit confirmed restart/shutdown through a narrow device capability. “Stop” cancels current output regardless of whether agent work continues; do not confuse audio stop with canceling the user's underlying instruction.

Expose timing spans for wake, endpointing, network send, STT ready/transcript, agent first commentary, TTS first audio, playout start and interrupt acknowledgement. Never log raw audio or credentials by default. Define freshness and sequence numbers for device metadata and reject stale/replayed media. Test link loss, server restart, GPU standby/wake and concurrent messages from the same person on Matrix.

## External references and licensing check

- [OHF-Voice Linux Voice Assistant](https://github.com/OHF-Voice/linux-voice-assistant) demonstrates wake/stop/button/LED and WebRTC noise processing, but is Home Assistant-oriented and documents a 512 MiB minimum, above this Pi's observed usable memory. Architecture reference only.
- [openWakeWord](https://github.com/dscripka/openWakeWord) is a possible wake engine; its code and bundled pretrained models have different licenses. Verify a suitable “Nova” model license and Pi CPU/latency before adding it.
- [sherpa-onnx keyword spotting](https://github.com/k2-fsa/sherpa/blob/master/docs/source/onnx/kws/index.rst) remains an **isolated Pi candidate**, not an accepted wake engine. The Nova lexicon and local runtime/model are staged outside the selected service. Ten seconds of synthetic silence measured about 9 seconds model load, 78 MiB process peak RSS and 4.6 seconds CPU time. On 2026-10-07, two consented 25-second live tests with three spoken "Nova" calls each returned **0/3** in both gated and continuous mode. A third, RAM-only capture returned no matches for the canonical pronunciation or four phoneme variants, on either raw or APM-processed PCM. The same Python decoder recognized `LIGHT_UP` in the model's bundled reference WAV, so the test harness and model are functional; these results do **not** validate the short German wake word. Do not deploy this wake candidate without a different, measured word/model strategy. Gating can still be reused around a suitable detector. Model redistribution license is unresolved, so weights are not committed.

The selected production Pi release has not been switched to this candidate.
