# Network context protocol v1

The device declares `network.transport.v1` and `network.probe.v1` as native
OpenClaw node commands. Device pairing, approved command surface and Gateway
command policy must all allow them. Generic node pairing alone is insufficient.
No existing OpenClaw protocol version or universal core tool is changed.

## Host authority

The host owns per-agent allowed contexts and a default context (`local` unless
explicitly changed). A context maps to one stable node ID; node names or LAN IPs
are not identity. Resolve that mapping from trusted agent/session execution
context before each operation and recheck live authority at dispatch. Never
accept an `agentId` in model-authored parameters as authority. An absent,
denied, offline or reassigned context fails; it must not select another network.

`client/transport.mjs` is the common reusable protocol client, outside the
firmware image. Supply:

```js
const transport = createNetworkTransport({
  resolveContexts: async (trustedIdentity) => ({
    default: 'local',
    contexts: [
      { id: 'local' },
      { id: 'node1', nodeId: 'example-node-id' },
    ],
  }),
  invoke: async ({ nodeId, command, sessionKey, params, signal, timeoutMs }) => {
    // Dispatch through the host's supported native node.invoke boundary.
    // The host validates current agent grants and propagates cancellation.
    // Decode the native payloadJSON into the result object returned here.
  },
});
```

The example is a callback contract, not an installed plugin or configuration
option. `local` dispatch remains owned by the host's local socket transport;
this device-protocol client rejects local instead of accidentally tunneling it.
An OpenClaw integration belongs in `openclaw-extensions` or the public SDK owner,
not in the flashed image. No native agent-context configuration field is
invented by this firmware.

Pass native `node.invoke`'s immutable `sessionKey` on every invocation. The
ESP32's metadata-aware handler requires it and binds handles to that session.
The node does not trust a session/agent field inside `paramsJSON`. The central
Gateway remains trusted: local node rules are a ceiling on what it may request,
not a replacement for per-agent host authorization. Granting raw transport to
an agent is broader than granting selected actions in a TV or other plugin.

Before enabling these commands for agents, the host integration must enforce
that policy at the shared native node-invoke boundary (including raw invokes
and CLI paths), not only in this convenience client. The custom command names
also need the Gateway's normal command allowlist/plugin policy; this firmware
does not add global allowlist entries or modify Gateway configuration.

## TCP and UDP

Every request includes `context`, matching the device's configured context ID.
The remaining transport fields are:

| op | Fields | Reply |
| --- | --- | --- |
| `open` | `protocol`: tcp/udp, `host`: canonical IPv4, `port`: 1–65535 | `id`, `state`: open/connecting |
| `poll` | `id` | open/connecting |
| `write` | `id`, `data`: canonical padded base64 | `written`: accepted byte count |
| `read` | `id` | `data` if available, or TCP `state: eof` |
| `shutdown` | `id` | TCP write half closed; reading remains possible |
| `close` | `id` | closed |

Errors are `{ state: "error", code: "..." }`. Authentication, missing native
session and wrong context use the native invocation error envelope instead.
There is no binary payload placed into the Gateway's JSON WebSocket parser.
TCP bytes (including target TLS) are opaque to the node. Reads are nonblocking.
The client handles connecting state, backpressure, partial writes and explicit
close. UDP datagram boundaries are preserved; v1 peers are connected/unicast.

Limits: four handles, 2048 decoded bytes per TCP read/write, 1200 per UDP
datagram, 6144 bytes of command parameters, 15 seconds idle and five minutes
absolute lifetime. Callers must serialize writes, respect acknowledgements and
close in `finally`. Expired handles do not reopen automatically. A host wanting
a connection beyond five minutes must explicitly create a fresh authorized
connection rather than replaying ambiguous side effects.

Disconnect/replacement invalidates all handles. Local configuration/reset
blocks operations before reboot. Host grant revocation must stop dispatch and
send best-effort handle cleanup; it must not wait for the agent's next action.
Idle expiry is the device-side bound if cleanup cannot reach it. Cleanup may
only close/cancel the original session-bound handle, never open a new one.

## Ping and scan

`network.probe.v1` accepts:

```json
{"context":"node1","op":"start","kind":"scan","targets":[{"host":"192.0.2.10","port":443}]}
```

For `kind: "ping"`, ports are omitted and ICMP rules apply. At most 32 explicit
targets, one active job, 200 ms per echo or 150 ms per TCP connect probe and
seven seconds total. Start returns a random `id`. Poll with `{context, op:
"poll", id}`; completion returns `state: "done"`, `complete`, `cancelled` and `results`.
`complete: false` explicitly marks a partial scan (for example, cancellation,
connection loss or the total deadline).
Cancel uses `op: "cancel"`. Job results expire after 30 seconds.

Each result has host, port (0 for ICMP), elapsedMs and observation `echo_reply`,
`tcp_open` or `no_confirmation`. A timeout/refused socket is not asserted to be
an offline host. The host expands target plans and interprets observations.
The node checks the local mode/rule and current connection generation again
before each network emission. Jobs run outside the native protocol callback
so polling, cancellation and disconnect handling remain available.
