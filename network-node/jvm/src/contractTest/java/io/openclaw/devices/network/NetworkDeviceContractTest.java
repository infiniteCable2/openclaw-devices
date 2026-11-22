/* SPDX-License-Identifier: AGPL-3.0-only */

package io.openclaw.devices.network;

import io.openclaw.devices.network.plugin.goe.GoEChargerProfile;
import io.openclaw.devices.network.plugin.goe.GoEChargerProfile.Match;
import io.openclaw.devices.network.plugin.goe.GoEChargeOperations;
import io.openclaw.devices.network.plugin.goe.GoEChargeOperations.StopState;

import java.nio.charset.StandardCharsets;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.HashMap;
import java.util.List;
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
        checkHistory();
        checkStop();
        System.out.println("Network device contracts passed.");
    }

    private static void checkHistory() {
        long start = 1_790_000_000_000L;
        long to = start + 24_000;
        var params = Map.of("plugin", "go-e", "deviceKey", KEY, "limit", 20, "from", start, "to", to);
        var request = GoEChargeOperations.parseHistoryRequest(params);
        var rows = new ArrayList<Map<String, Object>>();
        rows.add(Map.of("startUnix", start - 1, "endUnix", to + 10, "energy", 2, "still_running", false));
        for (int index = 0; index <= 24; index++) {
            rows.add(Map.of("startUnix", start + index * 1000, "endUnix", start + index * 1000 + 3000,
                    "energy", 5.25, "seconds_charged", "00:00:03", "still_running", false,
                    "link", "https://example.invalid/private-fixture", "ssid", "Example Wi-Fi"));
        }
        rows.add(Map.of("startUnix", start, "endUnix", to + 11, "energy", 1, "still_running", true));
        var page = GoEChargeOperations.historyPage(request, rows);
        var sessions = (List<?>) page.get("sessions");
        expect(KEY, page.get("deviceKey"));
        expect(true, page.get("hasMore"));
        expect(20, sessions.size());
        expect(Map.of("startUnix", start + 23_000, "endUnix", start + 26_000, "energy", 5.25,
                "seconds_charged", "00:00:03", "still_running", false), sessions.get(0));

        var nextParams = new HashMap<String, Object>(params);
        nextParams.put("offset", 20);
        var next = GoEChargeOperations.historyPage(GoEChargeOperations.parseHistoryRequest(nextParams), rows);
        expect(false, next.get("hasMore"));
        expect(4, ((List<?>) next.get("sessions")).size());
        rejects(() -> GoEChargeOperations.parseHistoryRequest(Map.of(
                "plugin", "go-e", "deviceKey", KEY, "limit", 3, "to", start, "from", start)));
        rejects(() -> GoEChargeOperations.parseHistoryRequest(Map.of(
                "plugin", "go-e", "deviceKey", KEY, "limit", 3, "offset", 2.5)));

        var timezone = ZoneId.of("Europe/Berlin");
        expect("https://data.v3.go-e.io/api/v1/direct_json?e=fixture%2Btoken&from=" + start
                        + "&to=" + to + "&timezone=Europe%2FBerlin",
                GoEChargeOperations.historyUri(
                        "https://data.v3.go-e.io/export?e=fixture%2Btoken", start, to, timezone).toString());
        rejects(() -> GoEChargeOperations.historyUri(
                "https://data.v3.go-e.io.example.invalid/export?e=fixture", start, to, timezone));
        rejects(() -> GoEChargeOperations.historyUri(
                "https://data.v3.go-e.io/export?e=fixture&%65=other", start, to, timezone));
        rejects(() -> GoEChargeOperations.historyUri(
                "https://data.v3.go-e.io@evil.example.invalid/export?e=fixture", start, to, timezone));
    }

    private static void checkStop() {
        expect(KEY, GoEChargeOperations.parseStopKey(Map.of("plugin", "go-e", "deviceKey", KEY)));
        rejects(() -> GoEChargeOperations.parseStopKey(Map.of("plugin", "go-e", "deviceKey", KEY, "frc", 2)));
        expect(StopState.CHARGING, GoEChargeOperations.stopState(KEY, Map.of("sse", KEY, "car", 2)));
        expect(StopState.ALREADY_STOPPED, GoEChargeOperations.stopState(KEY, Map.of("sse", KEY, "car", 4)));
        expect(StopState.UNCONFIRMED, GoEChargeOperations.stopState(KEY, Map.of("sse", "000124", "car", 4)));
        expect(StopState.UNCONFIRMED, GoEChargeOperations.stopState(KEY, Map.of("sse", KEY, "car", 0)));
        expect(true, GoEChargeOperations.confirmsStop(KEY, Map.of("sse", KEY, "car", 3, "frc", 1, "alw", false)));
        expect(false, GoEChargeOperations.confirmsStop(KEY, Map.of("sse", KEY, "car", 2, "frc", 1, "alw", false)));
        expect(false, GoEChargeOperations.confirmsStop(KEY, Map.of("sse", KEY, "car", 3, "frc", 0, "alw", false)));
    }

    private static void rejects(Runnable input) {
        try {
            input.run();
        } catch (IllegalArgumentException expected) {
            return;
        }
        throw new AssertionError("Invalid go-e request was accepted");
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
