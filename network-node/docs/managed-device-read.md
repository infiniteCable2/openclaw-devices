# Managed device plugins

`network.device.read.v2` uses the already paired node connection. The Gateway
resolves a configured device from the authorized inventory and supplies its
plugin ID and stable device key. For example:

```json
{"plugin":"go-e","deviceKey":"000123"}
```

The receiving node requires a locally enabled plugin, an explicitly approved
device key and an authorized current network. The plugin selects both the
discovery method and the permitted read. The request contains no address,
arbitrary URL, method or port. The node closes or cancels outstanding work
on revocation or network change. Network, discovery and HTTP failures retain
their separate result codes.

## Platform modules

The `network-node/jvm` library owns JVM device profiles and reusable TXT
snapshots. The Android consumer provides its connected-network identity,
network-bound DNS-SD and HTTP, and rechecks phone and session grants. Element
keeps the Matrix carrier, settings, pairing and Android permissions.

ESP32 modules use the existing firmware network and local policy owners. A
future firmware build can compile a reviewed C++ device profile for the
selected board and advertise the same operation after its contract checks
pass. Current ESP32 firmware advertises the documented transport and probe
commands, with their own authority rules.

## go-e read

The built-in go-e profile recognizes exactly six ASCII digits as the device
key. It discovers `_http._tcp` in the authorized network and accepts a
directly reachable private IPv4 at port 80. The same resolved callback's
TXT values are captured before checking the serial, manufacturer and device
type. Repeated, empty and conflicting serial fields cause rejection of a
candidate claiming the configured identity.

If there is no TXT serial and the instance name is the exact configured
`go-eCharger_…` name, the adapter may retain the address until the discovery
deadline. Conflicting TXT evidence for that instance invalidates this
fallback. The node uses a bounded GET to
`/api/status?filter=sse,car,alw,acu` and requires the response's string
`sse` to equal the configured key before returning a status or retaining an
address hint. Each cached-address read confirms the same identity.

The legacy `network.device.read` compatibility path selects a single
approved device from local configuration. The v2 operation carries the exact
configured key and remains suitable for multiple distinct chargers.

The JVM build's `contractTest` task checks identity, TXT snapshot isolation,
conflict rejection and compatibility with a name-only announcement.
