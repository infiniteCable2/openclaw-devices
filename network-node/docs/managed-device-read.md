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

Both stationary ESP board profiles share the same compiled device plugin
registry. On startup the firmware advertises `network.device.read.v2` if
local discovery is available and an enabled plugin has at least one approved
device. It checks the actual WLAN profile and its device grant on each call.
Stationary nodes store these grants in their setup portal. Mobile clients
manage their own equivalent settings and network identity.

The ESP network runtime supplies station-bound DNS-SD and bounded HTTP reads.
The compiled device profile supplies service criteria, fixed request and
response identity checks. The go-e address hint is kept in memory for up to
five minutes and scoped to the device key and current station link.

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

The JVM `contractTest` and C++ host checks cover identity, conflict rejection
and a name-only announcement. The JVM test also covers TXT snapshot isolation.
The firmware host and portal tests cover local grants on separate WLANs.
