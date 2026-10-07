"""ReSpeaker 2-Mic HAT GPIO button and three APA102-style SPI LEDs.

Importing this module has no hardware side effects. The Pi-only libraries are
loaded only when a device handle is opened, so state tests run off-device.
"""

from __future__ import annotations

from .controls import Indicator


_COLORS: dict[Indicator, tuple[int, int, int]] = {
    Indicator.UNPAIRED: (80, 0, 120),
    Indicator.MUTED: (180, 0, 0),
    Indicator.IDLE: (0, 20, 120),
    Indicator.LISTENING: (0, 130, 25),
    Indicator.SENSING: (0, 105, 105),
    Indicator.HEARING: (110, 170, 0),
    Indicator.PROCESSING: (180, 75, 0),
    Indicator.SPEAKING: (0, 110, 150),
}


def led_frame(indicator: Indicator, brightness: float = 0.2) -> bytes:
    """Build the 3-pixel SPI frame without needing GPIO/SPI libraries."""
    if not 0 <= brightness <= 1:
        raise ValueError("brightness must be a fraction in [0, 1]")
    # The 8-bit color channels provide smooth 0-100% control. At 20%, this is
    # effectively the former APA102 global brightness 6/31 default.
    colors = [_COLORS[indicator]] * 3

    frame = bytearray([0, 0, 0, 0])
    for red, green, blue in colors:
        frame.extend((0xFF, round(blue * brightness), round(green * brightness),
                      round(red * brightness)))
    frame.extend((255, 255, 255, 255))
    return bytes(frame)


class ReSpeakerLeds:
    def __init__(self, bus: int = 0, device: int = 0) -> None:
        import spidev

        self._spi = spidev.SpiDev()
        self._spi.open(bus, device)
        self._spi.max_speed_hz = 8_000_000
        self._last_frame: bytes | None = None

    def show(self, indicator: Indicator, brightness: float) -> None:
        frame = led_frame(indicator, brightness)
        if frame == self._last_frame:
            return
        self._spi.xfer2(list(frame))
        self._last_frame = frame

    def close(self) -> None:
        try:
            self._spi.xfer2(list(led_frame(Indicator.IDLE, brightness=0)))
        finally:
            self._spi.close()


class ReSpeakerButton:
    def __init__(self, gpio: int = 17) -> None:
        from gpiozero import Button

        self._button = Button(gpio, pull_up=True, bounce_time=0.035)

    @property
    def pressed(self) -> bool:
        return bool(self._button.is_pressed)

    def close(self) -> None:
        self._button.close()
