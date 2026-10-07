# Voiceassistant architecture: native-core boundary

## Responsibility split

```text
ReSpeaker microphones -> Pi capture -> AEC/NS + wake/stop/mute -> authenticated media transport
                                                            |
                                                            v
Gateway Talk/session -> existing STT -> OpenClaw agent/session -> existing TTS
                                                            |
                                                            v
Pi playout/volume -> speaker; the same played PCM + timing -> AEC reverse stream
```

The Pi is a **trusted media source**, but its own claims (speech probability, VAD, noise estimate, gain and device health) remain hints. Gateway policy, agent binding and authorization are server-owned. The server speech-focus/AGC2 path should still see unmodified level telemetry where possible; do not run an independently aggressive Pi AGC that erases its evidence. AEC and modest noise suppression are local because the Pi has the real loudspeaker reference and acoustic timing. Raw/relay/recording modes must bypass assistant-specific wake and speech processing by explicit mode, not by accidental reuse of the conversation input path.

## Existing OpenClaw seam and the gap

OpenClaw already has native Talk sessions, events, agent-prefixed session ownership and cryptographically signed device pairing with separate approval of the node command surface. Its native mobile Talk loop sends transcripts to Gateway chat and speaks replies. A Gateway-owned `gateway-relay` currently supports realtime-provider audio and transcription-only sessions. In the checked-out code, `talk.session.create` for `stt-tts` explicitly requires `managed-room`; `talk.session.appendAudio` rejects managed-room. Thus a small Linux client **cannot yet** simply stream its PCM into native Talk STT/TTS relay. That is a specific interface gap, not a reason to clone the agent loop.

Preferred server work: extend the native Talk contract with a narrowly scoped Gateway-owned `stt-tts` media relay (or reuse an equivalent upstream mechanism if it appears). Reuse Talk's session identity, event names, agent routing and interrupt/steering semantics. Implement media backpressure, bounded queues, output acknowledgements/cancel, idempotent reconnect and per-turn ordering there. STT/TTS should call the already-deployed providers and GPU readiness flow. A single device-bound session must not silently fall back to a different persona. Test the same agent history and tool rights as text/Matrix without special device-only business logic.

The **bound agent's** voice conversation profile must be resolved the same way as for Matrix RTC. For example_owner, that currently means `think off` for calls, commentary and the allowed message/tool surface. This is not a gateway-wide or device-type default; a later example_other, example_member or example_new device receives its own agent's configured profile. Do not duplicate settings as constants in the Pi client.

The alternative is a Talk node client with on-device STT/TTS, but it would bypass our proven server providers and burden a 416 MiB Pi. The heavyweight general node host is also not the intended Pi runtime. Do not introduce an unauthenticated custom WebSocket, a second conversation scheduler or a global bearer token as a shortcut.

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

## Controls and observability

Button gestures and LED state are local and work offline. Suggested states: blue idle, green listening, amber processing, cyan speaking, solid red muted, pulsing red error/unpaired. Colors/patterns are provisional until checked against the physical three-LED HAT; status must also be queryable without relying on color. Volume is software PCM gain with a safe cap and distinct levels. “Stop” cancels current output regardless of whether agent work continues; do not confuse audio stop with canceling the user's underlying instruction.

Expose timing spans for wake, endpointing, network send, STT ready/transcript, agent first commentary, TTS first audio, playout start and interrupt acknowledgement. Never log raw audio or credentials by default. Define freshness and sequence numbers for device metadata and reject stale/replayed media. Test link loss, server restart, GPU standby/wake and concurrent messages from the same person on Matrix.

## External references and licensing check

- [OHF-Voice Linux Voice Assistant](https://github.com/OHF-Voice/linux-voice-assistant) demonstrates wake/stop/button/LED and WebRTC noise processing, but is Home Assistant-oriented and documents a 512 MiB minimum, above this Pi's observed usable memory. Architecture reference only.
- [openWakeWord](https://github.com/dscripka/openWakeWord) is a possible wake engine; its code and bundled pretrained models have different licenses. Verify a suitable “Nova” model license and Pi CPU/latency before adding it.
- [sherpa-onnx keyword spotting](https://github.com/k2-fsa/sherpa/blob/master/docs/source/onnx/kws/index.rst) is another on-device candidate; benchmark on the real Pi, not a laptop.

No engine, model or third-party repository is selected as a runtime dependency yet.
