# zlib is built in this project (target apk_zlib, alias ZLIB::ZLIB); third-party find_package(ZLIB) calls
# resolve to it instead of a system zlib.
set(ZLIB_FOUND TRUE)
set(ZLIB_INCLUDE_DIRS ${ZLIB_DIR})
set(ZLIB_LIBRARIES apk_zlib)
set(ZLIB_VERSION_STRING "bundled")
