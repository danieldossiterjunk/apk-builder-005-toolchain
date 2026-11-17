// Force-included into every AOSP C++ file of this build (see CMakeLists.txt). AOSP's own libc++ makes some
// standard headers available transitively; other C++ libraries (the NDK's in C++23 mode, the build machine's)
// do not, and the AOSP sources then miss declarations such as memcpy, std::variant or std::numeric_limits.
#pragma once
#ifdef __cplusplus
#include <algorithm>
#include <climits>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <functional>
#include <limits>
#include <memory>
#include <optional>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>
#endif
