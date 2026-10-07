# Shared device enrollment and secure transport

This is the **target design**, not a deployed service. The user-facing procedure should be consistent for voice assistants, site bridges and later sensors, while each device receives only its own capability set. Wi-Fi enrollment, cryptographic device admission and permission assignment are three different actions.

Chosen security shape: **private network path where possible + certificate-validated WSS + native OpenClaw signed device identity and explicit capability approval**. These layers have different jobs and do not substitute for one another. A device on the same WLAN gets no implicit trust. A remote site uses the same OpenClaw identity and grants, not a second pairing system.

## 1. Short-lived local Wi-Fi setup

On a factory/unpaired device, a deliberate physical gesture starts a setup hotspot for at most ten minutes. The hotspot uses a unique random WPA2/WPA3 credential generated at preparation time, never a shared factory password. Because this Pi has no display, an administrator must obtain its setup QR/secret during preparation and attach it physically or use a trusted local setup utility. A nearby phone joins this protected AP and opens a small local setup page to choose the home SSID and submit its password. The page must not echo the password or leak it into logs; the saved credential belongs to NetworkManager's root-protected connection store. The AP has no Internet routing and is torn down after success, timeout or cancellation. Reopening it later requires the physical gesture and must not reveal stored Wi-Fi credentials.

This AP protects only the **local onboarding hop**; it does not make the device trusted by OpenClaw. HTTP on an open hotspot or a universal fixed password is not acceptable. The exact portal TLS/QR bootstrap needs a phone UX test: if local HTTPS pinning cannot be made understandable and verifiable, rely on the unique protected AP plus one-time setup secret and avoid claiming browser TLS that users will click through blindly.

## 2. Native Gateway pairing and capabilities

Prefer OpenClaw's existing device pairing: a device presents its signed identity, an administrator approves it, and a node's declared capabilities/commands require their own approval. The existing one-paste `oc-pair://` setup code is short-lived and can carry the Gateway endpoint and a TLS certificate pin; **do not** use a general `openclaw node run` command surface on this Pi merely to get pairing. That bootstrap path can approve the initial declared surface automatically, so the first surface must be empty/minimal and auditable. No `system.run`, filesystem or browser-proxy capability is needed for a voice endpoint.

For this fleet, prefer explicit approval even on LAN: OpenClaw currently allows silent loopback pairing and optional SSH/CIDR auto-approval. The server settings and existing nodes must be audited before changing that global policy. Device identity alone does not select a persona: a separate durable record binds device ID to `siteId`, allowed agent(s), communication modes and sensor/actuator capabilities. New or widened capabilities require explicit approval. Removal revokes the identity and active sessions.

The small voice client must implement only the native device identity and relevant Talk/media subset. If OpenClaw's protocol does not support this without an oversized node runtime, extend its public Gateway contract narrowly rather than inventing an unrelated long-lived token. Do not place setup codes or resulting credentials in repository config, release archives or command-line arguments.

## 3. Encrypted local and remote routes

Every application connection uses certificate-validated `wss://`; verify the expected hostname or pinned certificate and fail closed on TLS errors. On the home LAN, a stable name can resolve locally to the Gateway's private reverse proxy. For remote Linux devices and site bridges, use a private WireGuard-based overlay (Tailscale is a practical managed option) to the same stable service; keep the Gateway itself off the public Internet. A Pi can be an individual overlay peer; a remote site bridge can carry several small devices. Tiny sensors without a tunnel/client stack pair **through an approved site bridge** with separate sensor identities and narrowed delegated rights, never by inheriting the bridge's full privileges. Remote and LAN routes must not alter agent binding or permissions. The tunnel should be scoped to the Gateway endpoint for ordinary voice devices; only an explicitly approved site-admin bridge may reach a wider remote subnet.

The same onboarding UI may hide transport differences, but do not claim that an ESP32 can run the full Pi client. A private tunnel adds a network boundary; TLS and native pairing remain mandatory end-to-end for direct Gateway clients. A tiny sensor behind a bridge needs its own authenticated local link and Gateway-visible identity. Test cert renewal, DNS failover/local resolution, clock skew, device loss, credential rotation, revoke-while-connected and replay rejection before production.

## Acceptance criteria for first Pi

- Setup hotspot has unique credentials, physical start, bounded lifetime and no credential disclosure.
- Wi-Fi join persists only the selected network; AP exits and no setup portal remains reachable.
- Gateway rejects an unpaired device, unknown/changed public key and unapproved capability expansion.
- TLS is required on LAN and remote route; wrong certificate/pin is rejected.
- The device is bound to example_owner's agent voice profile, not a default or a second session namespace.
- Mute blocks every microphone mode, including future calls and live listen; revocation closes active media promptly.
