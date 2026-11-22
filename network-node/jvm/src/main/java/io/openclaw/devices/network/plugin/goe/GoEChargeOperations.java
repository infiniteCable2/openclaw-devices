/* SPDX-License-Identifier: AGPL-3.0-only */

package io.openclaw.devices.network.plugin.goe;

import java.io.UnsupportedEncodingException;
import java.net.URI;
import java.net.URLDecoder;
import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.regex.Pattern;

/** Wire contract and request data for explicitly assigned go-e charger operations. */
public final class GoEChargeOperations {
    public static final String HISTORY_COMMAND = "network.device.history.v1";
    public static final String STOP_COMMAND = "network.device.stop.v1";
    public static final String HISTORY_STATUS_PATH = "/api/status?filter=sse,dll";
    public static final String STOP_STATUS_PATH = "/api/status?filter=sse,car,frc,alw";
    public static final String STOP_PATH = "/api/set?frc=1";

    private static final String EXPORT_HOST = "data.v3.go-e.io";
    private static final long MAX_SAFE_INTEGER = 9_007_199_254_740_991L;
    private static final long MAX_TIME_MS = 8_640_000_000_000_000L;
    private static final int MAX_PAGE = 20;
    private static final Set<String> HISTORY_FIELDS = Set.of("plugin", "deviceKey", "limit", "offset", "from", "to");
    private static final Pattern DURATION = Pattern.compile("[0-9]{1,4}:[0-5][0-9]:[0-5][0-9]");

    private GoEChargeOperations() {}

    public static HistoryRequest parseHistoryRequest(Map<String, ?> params) {
        if (!HISTORY_FIELDS.containsAll(params.keySet())) {
            throw new IllegalArgumentException("Invalid go-e history parameters");
        }
        var deviceKey = targetKey(params);
        var limit = integer(params.get("limit"));
        var offset = params.containsKey("offset") ? integer(params.get("offset")) : Long.valueOf(0);
        var from = optionalInteger(params, "from");
        var to = optionalInteger(params, "to");
        if (limit == null || limit < 1 || limit > MAX_PAGE || offset == null) {
            throw new IllegalArgumentException("Invalid go-e history page");
        }
        return new HistoryRequest(deviceKey, limit.intValue(), offset, from, to);
    }

    public static String parseStopKey(Map<String, ?> params) {
        if (!params.keySet().equals(Set.of("plugin", "deviceKey"))) {
            throw new IllegalArgumentException("Invalid go-e stop parameters");
        }
        return targetKey(params);
    }

    private static String targetKey(Map<String, ?> params) {
        if (!GoEChargerProfile.PLUGIN_ID.equals(params.get("plugin"))
                || !(params.get("deviceKey") instanceof String deviceKey)
                || !GoEChargerProfile.isDeviceKey(deviceKey)) {
            throw new IllegalArgumentException("Invalid go-e target");
        }
        return deviceKey;
    }

    public record HistoryRequest(String deviceKey, int limit, long offset, Long from, Long to) {
        public HistoryRequest {
            if (!GoEChargerProfile.isDeviceKey(deviceKey) || limit < 1 || limit > MAX_PAGE
                    || offset < 0 || offset > MAX_SAFE_INTEGER - MAX_PAGE
                    || (from != null && !validTime(from)) || (to != null && !validTime(to))
                    || (from != null && to != null && from >= to)) {
                throw new IllegalArgumentException("Invalid go-e history request");
            }
        }
    }

    /** Call with the dll value read from the already verified charger. Never log either URL. */
    public static URI historyUri(String exportLink, long from, long to, ZoneId timezone) {
        if (exportLink == null || exportLink.length() > 4096 || !validTime(from) || !validTime(to)
                || from >= to || timezone == null) {
            throw new IllegalArgumentException("Unsupported go-e export");
        }
        final URI link;
        try {
            link = URI.create(exportLink);
        } catch (IllegalArgumentException invalid) {
            throw new IllegalArgumentException("Unsupported go-e export");
        }
        if (!"https".equalsIgnoreCase(link.getScheme()) || !EXPORT_HOST.equalsIgnoreCase(link.getHost())
                || !"/export".equals(link.getRawPath()) || link.getRawFragment() != null || link.getRawUserInfo() != null
                || (link.getPort() != -1 && link.getPort() != 443) || link.getRawQuery() == null) {
            throw new IllegalArgumentException("Unsupported go-e export");
        }
        String token = null;
        for (var field : link.getRawQuery().split("&")) {
            var pair = field.split("=", 2);
            if (!"e".equals(decodeExportField(pair[0]))) continue;
            if (pair.length != 2 || token != null) {
                throw new IllegalArgumentException("Unsupported go-e export");
            }
            token = decodeExportField(pair[1]);
        }
        if (token == null || token.isEmpty() || token.length() > 2048
                || token.codePoints().anyMatch(c -> Character.isWhitespace(c) || Character.isISOControl(c))) {
            throw new IllegalArgumentException("Unsupported go-e export");
        }
        return URI.create("https://" + EXPORT_HOST + "/api/v1/direct_json?e=" + encode(token)
                + "&from=" + from + "&to=" + to + "&timezone=" + encode(timezone.getId()));
    }

    /** Apply the start window before pagination and retain only the typed node reply fields. */
    public static Map<String, Object> historyPage(HistoryRequest request, Iterable<?> rows) {
        var sessions = new ArrayList<Session>();
        for (var entry : rows) {
            if (!(entry instanceof Map<?, ?> row) || !Boolean.FALSE.equals(row.get("still_running"))) continue;
            var start = integer(row.get("startUnix"));
            var end = integer(row.get("endUnix"));
            if (start == null || end == null || start < 1_000_000_000_000L || end > MAX_TIME_MS || end <= start
                    || (request.from != null && start < request.from) || (request.to != null && start >= request.to)
                    || !(row.get("energy") instanceof Number amount)) continue;
            var energy = amount.doubleValue();
            if (!Double.isFinite(energy) || energy < 0) continue;
            var duration = row.get("seconds_charged") instanceof String seconds
                    && DURATION.matcher(seconds).matches() ? seconds : null;
            sessions.add(new Session(start, end, energy, duration));
        }
        sessions.sort(Comparator.comparingLong(Session::end).thenComparingLong(Session::start).reversed());
        int offset = (int) Math.min(request.offset, sessions.size());
        int count = Math.min(request.limit, sessions.size() - offset);
        var page = new ArrayList<Map<String, Object>>(count);
        for (var session : sessions.subList(offset, offset + count)) {
            page.add(session.wireFields());
        }
        return Map.of("deviceKey", request.deviceKey, "sessions", List.copyOf(page),
                "hasMore", sessions.size() - offset > count);
    }

    public static StopState stopState(String deviceKey, Map<String, ?> status) {
        if (!(status.get("sse") instanceof String serial) || !GoEChargerProfile.confirmsIdentity(deviceKey, serial)) {
            return StopState.UNCONFIRMED;
        }
        var car = integer(status.get("car"));
        if (car == null) return StopState.UNCONFIRMED;
        if (car == 2) return StopState.CHARGING;
        return car == 1 || car == 3 || car == 4 ? StopState.ALREADY_STOPPED : StopState.UNCONFIRMED;
    }

    public static boolean confirmsStop(String deviceKey, Map<String, ?> status) {
        return stopState(deviceKey, status) == StopState.ALREADY_STOPPED
                && Long.valueOf(1).equals(integer(status.get("frc")))
                && Boolean.FALSE.equals(status.get("alw"));
    }

    public enum StopState { CHARGING, ALREADY_STOPPED, UNCONFIRMED }

    private record Session(long start, long end, double energy, String duration) {
        Map<String, Object> wireFields() {
            if (duration == null) {
                return Map.of("startUnix", start, "endUnix", end, "energy", energy, "still_running", false);
            }
            return Map.of("startUnix", start, "endUnix", end, "energy", energy, "still_running", false,
                    "seconds_charged", duration);
        }
    }

    private static boolean validTime(long value) {
        return value >= -MAX_TIME_MS && value <= MAX_TIME_MS;
    }

    private static Long optionalInteger(Map<String, ?> params, String field) {
        if (!params.containsKey(field)) return null;
        var value = integer(params.get(field));
        if (value == null) throw new IllegalArgumentException("Invalid go-e history timestamp");
        return value;
    }

    private static Long integer(Object value) {
        if (!(value instanceof Number number)) return null;
        double amount = number.doubleValue();
        return Math.abs(amount) <= MAX_SAFE_INTEGER && amount == Math.rint(amount) ? (long) amount : null;
    }

    private static String decodeExportField(String value) {
        try {
            return URLDecoder.decode(value, StandardCharsets.UTF_8.name());
        } catch (UnsupportedEncodingException | IllegalArgumentException invalid) {
            throw new IllegalArgumentException("Unsupported go-e export");
        }
    }

    private static String encode(String value) {
        try {
            return URLEncoder.encode(value, StandardCharsets.UTF_8.name());
        } catch (UnsupportedEncodingException invalid) {
            throw new IllegalArgumentException("Unsupported go-e export");
        }
    }
}
