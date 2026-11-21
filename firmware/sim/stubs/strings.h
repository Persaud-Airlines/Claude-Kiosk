// Portable strcasecmp: POSIX <strings.h> on macOS/Linux, the MSVC/MinGW equivalents on Windows.
// Shared UI code (ui/i18n.cpp, ui/kiosk_app.cpp) includes <strings.h>; this stub is found first on the
// simulator's include path only, so the ESP-IDF firmware build is unaffected.
#pragma once
#ifdef _WIN32
#include <string.h>
#define strcasecmp _stricmp
#define strncasecmp _strnicmp
#else
#include_next <strings.h>
#endif
