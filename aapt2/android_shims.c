/*
 * APK Builder 005 Stage 0: link-time shim for the Android build of AAPT2.
 *
 * libincfs calls selinux_android_restorecon() only when it mounts an incremental file system, which AAPT2
 * never does. Linking libselinux for that one call would also pull in libsepol and pcre2, so this build
 * provides the function instead: it fails with ENOSYS and writes a line to stderr, so a call can never pass
 * silently. Licensed under the Apache License, Version 2.0.
 */
#include <errno.h>
#include <stdio.h>

int selinux_android_restorecon(const char* file, unsigned int flags) {
    (void)flags;
    fprintf(stderr, "aapt2: selinux_android_restorecon(%s) is not available in this build\n", file ? file : "");
    errno = ENOSYS;
    return -1;
}
