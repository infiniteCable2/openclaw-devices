/* SPDX-License-Identifier: AGPL-3.0-only */

package io.openclaw.devices.network.plugin.goe;

import io.openclaw.devices.network.DnsSdTxt;

import java.util.List;

/** The built-in read-only go-e device plugin. */
public final class GoEChargerProfile {
    public static final String NODE_COMMAND = "network.device.read.v2";
    public static final String PLUGIN_ID = "go-e";
    public static final String SERVICE_TYPE = "_http._tcp";
    public static final int HTTP_PORT = 80;
    public static final String STATUS_PATH = "/api/status?filter=sse,car,alw,acu";
    public static final List<String> TELEMETRY_FIELDS = List.of(
            "modelStatus", "nrg", "pha", "fsp", "psm", "cus", "wh", "cdi", "amp", "cbl", "dwo", "whg", "whs",
            "whb", "who", "fhz", "avgfhz", "gsa", "err", "typ", "fwv", "tma", "adi", "lck", "ffb", "eto");
    public static final String TELEMETRY_PATH = STATUS_PATH + "," + String.join(",", TELEMETRY_FIELDS);
    public static final long MAX_STATUS_BYTES = 8192;

    private static final String INSTANCE_PREFIX = "go-eCharger_";
    private static final String DEVICE_TYPE_PREFIX = "go-eCharger";

    private GoEChargerProfile() {}

    public static boolean isDeviceKey(String value) {
        return value != null && value.length() == 6 && value.chars().allMatch(c -> c >= '0' && c <= '9');
    }

    public static String instanceKey(String serviceName) {
        if (serviceName == null || !serviceName.regionMatches(true, 0, INSTANCE_PREFIX, 0, INSTANCE_PREFIX.length())) {
            return null;
        }
        var suffix = serviceName.substring(INSTANCE_PREFIX.length());
        return isDeviceKey(suffix) ? suffix : null;
    }

    public static Observation inspect(String serviceName, int port, DnsSdTxt txt, String expectedKey) {
        if (!isDeviceKey(expectedKey)) {
            throw new IllegalArgumentException("Invalid go-e device key");
        }
        var nameKey = instanceKey(serviceName);
        boolean namedTarget = expectedKey.equals(nameKey);
        var serials = txt.values("serial");
        boolean serialMatches = serials.size() == 1 && expectedKey.equals(serials.get(0));
        boolean nameFallback = namedTarget && serials.isEmpty();
        var manufacturers = txt.values("manufacturer");
        var deviceTypes = txt.values("devicetype");
        boolean manufacturerMatches = manufacturers.size() == 1 && "go-e".equalsIgnoreCase(manufacturers.get(0));
        boolean typeMatches = deviceTypes.size() == 1 && deviceTypes.get(0) != null &&
                deviceTypes.get(0).regionMatches(true, 0, DEVICE_TYPE_PREFIX, 0, DEVICE_TYPE_PREFIX.length());
        boolean claimsTarget = namedTarget || (serialMatches && manufacturerMatches && typeMatches);

        if ((!serialMatches && !nameFallback) || (serialMatches && nameKey != null && !namedTarget)) {
            return new Observation(namedTarget, claimsTarget,
                    namedTarget || serialMatches ? Match.SERIAL_CONFLICT : Match.OTHER_DEVICE);
        }
        if (port != HTTP_PORT || !fieldAllowed(manufacturers, manufacturerMatches, nameFallback) ||
                !fieldAllowed(deviceTypes, typeMatches, nameFallback)) {
            return new Observation(namedTarget, claimsTarget, Match.SERVICE_MISMATCH);
        }
        return new Observation(namedTarget, claimsTarget, nameFallback ? Match.NAME_FALLBACK : Match.IDENTIFIED);
    }

    private static boolean fieldAllowed(List<String> values, boolean matches, boolean allowMissing) {
        return matches || (allowMissing && values.isEmpty());
    }

    public static boolean confirmsIdentity(String expectedKey, String reportedSerial) {
        return isDeviceKey(expectedKey) && expectedKey.equals(reportedSerial);
    }

    public record Observation(boolean namedTarget, boolean claimsTarget, Match match) {}

    public enum Match {
        OTHER_DEVICE, SERIAL_CONFLICT, SERVICE_MISMATCH, NAME_FALLBACK, IDENTIFIED
    }
}
