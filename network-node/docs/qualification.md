# Hardware qualification

No device is deployed or paired by adding this source. Run against an isolated
Gateway and synthetic test endpoints first. Record firmware/source revision,
board/flash variant, dependency lock, measured free/minimum heap, results and
the cleanup performed. Do not record passwords, tokens or network payloads.

- First boot: unique serial setup password, WPA2 AP, authenticated page/API;
  no credential appears in a status response. Test bad/missing Basic auth,
  missing/wrong CSRF, cross-origin requests and oversized input.
- Wi-Fi: valid/invalid SSID/password, no DHCP, link loss for more than 30 s,
  restored link, multiple AP clients. Setup AP closes after a station IP returns;
  test a short outage that restores the same IP before the old TCP socket times
  out: the node must explicitly replace the Gateway connection and recover.
  failed OpenClaw auth alone does not open it. Test saving a corrected Wi-Fi
  configuration from the recovery AP.
- Credentials: web password change invalidates old Basic credentials and old
  CSRF; AP password remains valid. Confirm blank password preservation and
  explicit open-Wi-Fi selection.
- TLS: valid public/custom CA, wrong hostname/CA, missing clock, browser clock
  synchronization, unreachable Gateway. No plaintext or skipped verification.
- Pairing: native challenge/signature and Gateway approval; reboot reuses the
  same device identity and scoped token. Rejected/revoked token pauses without
  shared-secret fallback. New Gateway URI does not reuse the old session.
- Transport: actual host plugin path through the common adapter, TCP echo,
  target TLS handshake, partial writes, EOF/half-close, UDP request/reply,
  oversized datagrams, capacity, idle/absolute expiry and cancellation.
- Policy: allowed and denied targets/ports/protocols in allowlist mode; separate
  ping/scan switches; admin mode; management/loopback/link-local exclusions;
  matching/wrong/unknown/off-subnet MAC pin. Unknown ARP must fail closed.
- Contexts: two contexts with identical private IP targets, agent allowed only
  one, missing/forged session metadata, cross-session handle reuse, reassignment
  and grant revocation. No local-network fallback or session replay.
- Probes: real ICMP echo, no reply, refused/open TCP port, partial/cancelled
  scan, reconnect during a running job, per-target/total budgets.
- Reset: authenticated reset and physical GPIO0 hold after boot. Observe a new
  identity/password and empty settings. No older Gateway data or agent state is
  restored. Revoke the previous Gateway pairing independently.
- Soak: repeated Wi-Fi/Gateway loss during concurrent traffic and HTTP use;
  verify minimum heap, task stacks, bounded socket count and watchdog stability.

Clean generated build trees, test captures, temporary endpoints and staging
installations after consumers finish. Keep only source, concise verification
evidence and any explicitly required validated device recovery image. Initial
development does not replace or qualify an existing production rollback.
