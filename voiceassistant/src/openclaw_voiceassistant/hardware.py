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
    Indicator.PROCESSING: (180, 75, 0),
    Indicator.SPEAKING: (0, 110, 150),
}


def led_frame(indicator: Indicator, volume: float, brightness: int = 6) -> bytes:
    """Build the 3-pixel SPI frame without needing GPIO/SPI libraries."""
    if not 0 <= volume <= 1:
        raise ValueError("volume must be a fraction in [0, 1]")
    if not 0 <= brightness <= 31:
        raise ValueError("brightness must be in [0, 31]")
    if indicator == Indicator.VOLUME:
        lit = min(3, max(1, int(volume * 3 + 0.999)))
        colors = [(255, 255, 255) if index < lit else (0, 0, 0) for index in range(3)]
    else:
        colors = [_COLORS[indicator]] * 3

    frame = bytearray([0, 0, 0, 0])
    for red, green, blue in colors:
        if brightness == 0:
            red = green = blue = 0
        pixel_brightness = brightness if (red, green, blue) != (0, 0, 0) else 0
        frame.extend((0xE0 | pixel_brightness, blue, green, red))
    frame.extend((255, 255, 255, 255))
    return bytes(frame)


class ReSpeakerLeds:
    def __init__(self, bus: int = 0, device: int = 0) -> None:
        import spidev

        self._spi = spidev.SpiDev()
        self._spi.open(bus, device)
        self._spi.max_speed_hz = 8_000_000
        self._last_frame: bytes | None = None

    def show(self, indicator: Indicator, volume: float) -> None:
        frame = led_frame(indicator, volume)
        if frame == self._last_frame:
            return
        self._spi.xfer2(list(frame))
        self._last_frame = frame

    def close(self) -> None:
        try:
            self._spi.xfer2(list(led_frame(Indicator.IDLE, 0, brightness=0)))
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
