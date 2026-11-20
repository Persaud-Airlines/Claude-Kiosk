#pragma once
#include <ctime>
#include <string>

namespace dt {

/** SNTP with time.microsoft.com, falling back to pool.ntp.org and time.google.com. */
class TimeSync {
public:
    static void start();
    static bool synced();
    static void setPosixTz(const std::string &posix);
    /** "10:14:22 AM" in the school's timezone. */
    static std::string localClock();
    static std::string utcClock();
    /** RFC 3339 UTC timestamp for event payloads, empty when the clock is not yet valid. */
    static std::string isoUtcNow();
};

}  // namespace dt
