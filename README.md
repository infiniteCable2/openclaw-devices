# OpenClaw Devices

This repository holds **device-side** software for OpenClaw-connected hardware. The first device is the [Raspberry Pi voice assistant](voiceassistant/README.md); later site bridges and sensors can live in separate top-level subdirectories. Each device must have its own deployable artifact and installation guide, so deployment never requires cloning the entire monorepo onto a small target.

Server-side OpenClaw integration belongs in the OpenClaw fork or `openclaw-extensions`, not inside a device image. Device clients transport media and device events; OpenClaw remains responsible for agent sessions, tools, routing and authorization. Legacy Voicecore and Ghostbox sources are references only, not runtime dependencies.

Do not commit pairing credentials, certificates, local recordings, model downloads or hardware-specific secrets. Machine-local `AGENTS.md` instructions and `.local/` data are ignored. A new device is not trusted merely because it is on the LAN: it must be enrolled, bound to an allowed agent and revocable.

Status: the Pi hardware was inventoried and the obsolete Ghostbox runtime retired. The new OpenClaw voice client is **not yet deployed or paired**; see the [integration design](voiceassistant/docs/architecture.md) for the device-audio transport and pairing work that remains.
