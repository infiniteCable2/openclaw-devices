#pragma once
#include <cstring>

namespace netnode {
// A bounded, newline-framed request; discard an entire overlong line.
class SetupCommand {
    char line[64]{};
    size_t used = 0;
    bool overflow = false;
public:
    bool feed(char value) {
        if (value == '\n') {
            bool match = !overflow && !std::strcmp(line, "netnode setup-access v1");
            used = 0; overflow = false; line[0] = '\0';
            return match;
        }
        if (value == '\r') return false;
        if (value == '\0' || used >= sizeof(line) - 1) overflow = true;
        if (!overflow) { line[used++] = value; line[used] = '\0'; }
        return false;
    }
};
}
