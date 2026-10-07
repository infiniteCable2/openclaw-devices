# Voiceassistant installation status and bring-up

There is **no production installation procedure yet**: the device-control core is testable, but the encrypted OpenClaw media transport, Wi-Fi provisioning page, wake/stop models and AEC/playout loop have not been implemented. Do not install this package as a service or point it at the production Gateway.

## Local, hardware-free validation

With Python 3.11 or newer in `voiceassistant/`:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

These tests cover fail-closed mute/pairing, wake timeout, stop/playback cancellation, held-button volume changes and the three-LED SPI frame format. They do **not** prove ReSpeaker audio, acoustic echo cancellation, TLS/pairing or agent behavior.

## Pi inventory to repeat before device integration

On the Raspberry Pi Zero 2 W, use read-only checks first:

```sh
cat /etc/os-release
aplay -l
arecord -l
ls -l /dev/spidev0.*
grep -E '^(dtparam=(spi|i2s)|dtoverlay=)' /boot/firmware/config.txt
```

Expected from the previous inventory: `seeed2micvoicec`, `/dev/spidev0.0` and `.1`, `dtparam=spi=on`, `dtparam=i2s=on`, and `dtoverlay=respeaker-2mic-v1_0`. Confirm rather than hard-code card index. The target's temporary setup password must be changed or locked before production. Never copy it into this repository.

Device-side installation will later package only this `voiceassistant/` subtree, create a least-privilege service identity, install hardware libraries, enroll over the guarded setup hotspot, verify the Gateway's certificate and device pairing, and start a systemd unit with an explicit rollback. Those steps need on-device tests and a separate deployment authorization.
