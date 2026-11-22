/* SPDX-License-Identifier: AGPL-3.0-only */

package io.openclaw.devices.network;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Collections;
import java.util.HashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/** The TXT fields from one resolved DNS-SD announcement. */
public final class DnsSdTxt {
    private final Map<String, List<String>> fields;

    private DnsSdTxt(Map<String, List<String>> fields) {
        this.fields = fields;
    }

    public static DnsSdTxt capture(Map<String, byte[]> attributes) {
        var snapshot = new HashMap<String, List<String>>();
        for (var entry : attributes.entrySet()) {
            var bytes = entry.getValue();
            var value = bytes == null ? null : new String(bytes.clone(), StandardCharsets.UTF_8);
            snapshot.computeIfAbsent(entry.getKey().toLowerCase(Locale.ROOT), ignored -> new ArrayList<>()).add(value);
        }
        // A present key with no value differs from an absent key.
        snapshot.replaceAll((key, values) -> Collections.unmodifiableList(values));
        return new DnsSdTxt(Map.copyOf(snapshot));
    }

    public List<String> values(String key) {
        return fields.getOrDefault(key.toLowerCase(Locale.ROOT), List.of());
    }
}
