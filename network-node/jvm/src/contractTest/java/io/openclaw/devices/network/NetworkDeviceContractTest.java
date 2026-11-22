/* SPDX-License-Identifier: AGPL-3.0-only */

package io.openclaw.devices.network;

import io.openclaw.devices.network.plugin.goe.GoEChargerProfile;
import io.openclaw.devices.network.plugin.goe.GoEChargerProfile.Match;

import java.nio.charset.StandardCharsets;
import java.util.Arrays;
import java.util.HashMap;
import java.util.Map;

public final class NetworkDeviceContractTest {
    private static final String KEY = "000123";
    private static final String NAME = "go-eCharger_" + KEY;

    public static void main(String[] args) {
        var raw = matchingTxt();
        var snapshot = DnsSdTxt.capture(raw);
        Arrays.fill(raw.get("serial"), (byte) 0);
        Arrays.fill(raw.get("manufacturer"), (byte) 0);
        raw.clear();
        expect(Match.IDENTIFIED, GoEChargerProfile.inspect(NAME, 80, snapshot, KEY).match());
        expect(Match.IDENTIFIED, GoEChargerProfile.inspect("Custom name", 80, snapshot, KEY).match());
        expect(Match.SERIAL_CONFLICT, GoEChargerProfile.inspect("go-eCharger_000124", 80, snapshot, KEY).match());
        expect(Match.SERVICE_MISMATCH, GoEChargerProfile.inspect(NAME, 443, snapshot, KEY).match());
        expect(Match.NAME_FALLBACK, inspect(NAME, Map.of()));
        expect(Match.OTHER_DEVICE, inspect("Unrelated device", Map.of()));
        expect(Match.SERIAL_CONFLICT, inspect(NAME, Map.of("serial", bytes("000124"))));
        expect(Match.SERIAL_CONFLICT, inspect(NAME, Map.of("Serial", bytes(KEY), "serial", bytes(KEY))));
        expect(Match.SERVICE_MISMATCH, inspect(NAME, Map.of("manufacturer", bytes("Different vendor"))));
        var noValue = new HashMap<String, byte[]>();
        noValue.put("serial", null);
        expect(Match.SERIAL_CONFLICT, inspect(NAME, noValue));
        expect(true, GoEChargerProfile.confirmsIdentity(KEY, KEY));
        expect(false, GoEChargerProfile.confirmsIdentity(KEY, "000124"));
        expect(false, GoEChargerProfile.confirmsIdentity("123", "123"));
        expect(false, GoEChargerProfile.confirmsIdentity(KEY, null));
        System.out.println("Network device contract passed (14 checks).");
    }

    private static Match inspect(String name, Map<String, byte[]> attributes) {
        return GoEChargerProfile.inspect(name, 80, DnsSdTxt.capture(attributes), KEY).match();
    }

    private static Map<String, byte[]> matchingTxt() {
        return new HashMap<>(Map.of(
                "serial", bytes(KEY),
                "manufacturer", bytes("go-e"),
                "devicetype", bytes("go-eCharger_V4")));
    }

    private static byte[] bytes(String value) {
        return value.getBytes(StandardCharsets.UTF_8);
    }

    private static void expect(Object expected, Object actual) {
        if (!expected.equals(actual)) {
            throw new AssertionError("Expected " + expected + ", got " + actual);
        }
    }
}
