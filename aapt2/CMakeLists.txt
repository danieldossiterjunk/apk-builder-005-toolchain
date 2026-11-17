# AAPT2 from AOSP sources, for APK Builder 005 Stage 0 (approval D-03 option A).
#
# Builds only AAPT2 and the libraries it links, from one pinned AOSP release. Source lists are generated from
# the release's own Android.bp files (gen_sources.py); this file holds only what Soong would otherwise supply:
# include directories, compile definitions, generated headers and the link order.
#
#   cmake -S aapt2 -B build -DAOSP_SRC=<dir with base/, core/, libbase/, ...> -DPROTOC=<host protoc>
#         [desktop: -DCMAKE_CXX_FLAGS=-stdlib=libc++ -DCMAKE_EXE_LINKER_FLAGS="-stdlib=libc++ -static-libstdc++"]
#         [-DCMAKE_TOOLCHAIN_FILE=<ndk>/build/cmake/android.toolchain.cmake -DANDROID_ABI=arm64-v8a
#          -DANDROID_PLATFORM=android-30 -DANDROID_STL=c++_static]
#
# Deliberate differences from the upstream device build (each also reported in BUILD-NOTES.txt):
#  * the Android executable is fully static (-static), so it runs from an app's native library directory with no
#    other files (the desktop one links the C library dynamically);
#  * standard headers are force-included (std_prelude.h): AOSP relies on AOSP libc++'s transitive includes;
#  * zlib is upstream zlib (the recipe's pinned commit), not AOSP's Chromium-derived external/zlib;
#  * libandroidfw leaves out CursorWindow/Backup* (need libbinder; AAPT2 never calls them);
#  * on Android, libincfs is linked as upstream but selinux_android_restorecon() (used only when mounting an
#    incremental file system, which AAPT2 never does) is a stub that fails with ENOSYS, so libselinux, libsepol
#    and pcre2 are not linked at all;
#  * the read-only aconfig flags of android.content.res come from flags/android_content_res.values.
cmake_minimum_required(VERSION 3.22)
project(apkbuilder_aapt2 C CXX ASM)

if(NOT AOSP_SRC OR NOT EXISTS ${AOSP_SRC}/base/tools/aapt2/Android.bp)
    message(FATAL_ERROR "set -DAOSP_SRC to the directory that holds base/, core/, libbase/ ...")
endif()
if(NOT PROTOC OR NOT EXISTS ${PROTOC})
    message(FATAL_ERROR "set -DPROTOC to a protoc built for this machine from ${AOSP_SRC}/protobuf")
endif()
find_package(Python3 REQUIRED COMPONENTS Interpreter)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_EXTENSIONS ON)
set(CMAKE_CXX_STANDARD 23)          # Android.bp: cpp_std "gnu++2b"
set(CMAKE_CXX_EXTENSIONS ON)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

if(NOT ANDROID AND NOT CMAKE_CXX_FLAGS MATCHES "stdlib=libc\\+\\+")
    message(WARNING "desktop build without -stdlib=libc++: AOSP code expects LLVM's C++ library; pass "
                    "-DCMAKE_CXX_FLAGS=-stdlib=libc++ (and -stdlib=libc++ -static-libstdc++ for the linker)")
endif()
if(ANDROID)
    set(VARIANT android)
    if(NOT ANDROID_STL STREQUAL "c++_static")
        message(FATAL_ERROR "use -DANDROID_STL=c++_static for a static executable")
    endif()
else()
    set(VARIANT host)
endif()
set(S ${AOSP_SRC})
set(GEN ${CMAKE_BINARY_DIR}/gen)
file(MAKE_DIRECTORY ${GEN})

add_compile_definitions(_FILE_OFFSET_BITS=64)
add_compile_options("$<$<COMPILE_LANGUAGE:C,CXX>:-Wno-attributes>" "$<$<COMPILE_LANGUAGE:C,CXX>:-ffunction-sections>"
                    "$<$<COMPILE_LANGUAGE:C,CXX>:-fdata-sections>")

# ---------------------------------------------------------------- source lists from Android.bp
execute_process(
    COMMAND ${Python3_EXECUTABLE} -I ${CMAKE_CURRENT_SOURCE_DIR}/gen_sources.py ${S} ${VARIANT} ${GEN}/sources.cmake
    RESULT_VARIABLE rc)
if(NOT rc EQUAL 0)
    message(FATAL_ERROR "gen_sources.py failed")
endif()
include(${GEN}/sources.cmake)

# ---------------------------------------------------------------- third-party libraries (their own CMake)
# zlib
set(ZLIB_DIR ${S}/zlib)
add_library(apk_zlib STATIC
    ${ZLIB_DIR}/adler32.c ${ZLIB_DIR}/compress.c ${ZLIB_DIR}/crc32.c ${ZLIB_DIR}/deflate.c ${ZLIB_DIR}/gzclose.c
    ${ZLIB_DIR}/gzlib.c ${ZLIB_DIR}/gzread.c ${ZLIB_DIR}/gzwrite.c ${ZLIB_DIR}/infback.c ${ZLIB_DIR}/inffast.c
    ${ZLIB_DIR}/inflate.c ${ZLIB_DIR}/inftrees.c ${ZLIB_DIR}/trees.c ${ZLIB_DIR}/uncompr.c ${ZLIB_DIR}/zutil.c)
target_include_directories(apk_zlib PUBLIC ${ZLIB_DIR})
target_compile_definitions(apk_zlib PRIVATE Z_HAVE_UNISTD_H HAVE_UNISTD_H)
target_compile_options(apk_zlib PRIVATE -w)
add_library(ZLIB::ZLIB ALIAS apk_zlib)
set(ZLIB_FOUND TRUE)
set(ZLIB_INCLUDE_DIR ${ZLIB_DIR} CACHE PATH "" FORCE)
set(ZLIB_INCLUDE_DIRS ${ZLIB_DIR})
set(ZLIB_LIBRARY apk_zlib CACHE STRING "" FORCE)
set(ZLIB_LIBRARIES apk_zlib)
list(PREPEND CMAKE_MODULE_PATH ${CMAKE_CURRENT_SOURCE_DIR}/cmake)

# libpng (static only)
set(PNG_SHARED OFF CACHE BOOL "" FORCE)
set(PNG_STATIC ON CACHE BOOL "" FORCE)
set(PNG_TESTS OFF CACHE BOOL "" FORCE)
set(PNG_TOOLS OFF CACHE BOOL "" FORCE)
set(PNG_EXECUTABLES OFF CACHE BOOL "" FORCE)
set(PNG_FRAMEWORK OFF CACHE BOOL "" FORCE)
set(SKIP_INSTALL_ALL ON CACHE BOOL "" FORCE)
set(M_LIBRARY m CACHE STRING "" FORCE)
add_subdirectory(${S}/libpng ${CMAKE_BINARY_DIR}/libpng EXCLUDE_FROM_ALL)

# expat, compiled as its Android.bp does: AOSP's single expat_config.h (lib/) serves every target and relies on
# -include stdio.h so that __BIONIC__ / __GLIBC__ are known before it is read
add_library(apk_expat STATIC ${S}/expat/expat/lib/xmlparse.c ${S}/expat/expat/lib/xmlrole.c ${S}/expat/expat/lib/xmltok.c)
target_include_directories(apk_expat PUBLIC ${S}/expat/expat/lib)
target_compile_definitions(apk_expat PRIVATE HAVE_EXPAT_CONFIG_H)
target_compile_options(apk_expat PRIVATE -fno-strict-aliasing -include stdio.h -Wno-format)
add_library(expat::expat ALIAS apk_expat)

# fmt (libbase)
set(FMT_INSTALL OFF CACHE BOOL "" FORCE)
add_subdirectory(${S}/fmtlib ${CMAKE_BINARY_DIR}/fmtlib EXCLUDE_FROM_ALL)

# abseil, then protobuf (runtime libraries only; protoc comes from -DPROTOC)
set(ABSL_PROPAGATE_CXX_STD ON CACHE BOOL "" FORCE)
set(ABSL_BUILD_TESTING OFF CACHE BOOL "" FORCE)
set(ABSL_ENABLE_INSTALL OFF CACHE BOOL "" FORCE)
add_subdirectory(${S}/abseil-cpp ${CMAKE_BINARY_DIR}/abseil-cpp EXCLUDE_FROM_ALL)
set(protobuf_BUILD_TESTS OFF CACHE BOOL "" FORCE)
set(protobuf_BUILD_CONFORMANCE OFF CACHE BOOL "" FORCE)
set(protobuf_BUILD_EXAMPLES OFF CACHE BOOL "" FORCE)
set(protobuf_BUILD_PROTOC_BINARIES OFF CACHE BOOL "" FORCE)
set(protobuf_BUILD_LIBPROTOC OFF CACHE BOOL "" FORCE)
set(protobuf_BUILD_LIBUPB OFF CACHE BOOL "" FORCE)
set(protobuf_BUILD_SHARED_LIBS OFF CACHE BOOL "" FORCE)
set(protobuf_INSTALL OFF CACHE BOOL "" FORCE)
set(protobuf_WITH_ZLIB OFF CACHE BOOL "" FORCE)
set(protobuf_ABSL_PROVIDER module CACHE STRING "" FORCE)
add_subdirectory(${S}/protobuf ${CMAKE_BINARY_DIR}/protobuf EXCLUDE_FROM_ALL)

# ---------------------------------------------------------------- shared include directories (Soong header libs)
set(AOSP_INCLUDES
    ${S}/libbase/include
    ${S}/logging/liblog/include
    ${S}/core/include
    ${S}/core/libcutils/include
    ${S}/core/libutils/include
    ${S}/core/libutils/binder/include
    ${S}/core/libsystem/include
    ${S}/libziparchive/include
    ${S}/libziparchive/incfs_support/include
    ${S}/incremental_delivery/incfs/util/include
    ${S}/incremental_delivery/incfs/include
    ${S}/incremental_delivery/incfs/kernel-headers
    ${S}/incremental_delivery/sysprop/include
    ${S}/base/libs/androidfw/include
    ${S}/base/libs/androidfw/include_pathutils
    ${S}/base/cmds/idmap2/libidmap2_policies/include
    ${S}/native/include
    ${S}/native/libs/binder/include
    ${S}/soong/cc/libbuildversion/include
    ${S}/googletest/googletest/include
    ${S}/boringssl/include
    ${S}/selinux/libselinux/include
    ${S}/unwinding/libbacktrace/include
    ${GEN}/flags
    ${S}/fmtlib/include
)

# AOSP code is written against AOSP's libc++, which still provides some standard headers transitively; with the
# NDK's or the build machine's C++ library the same files may miss <cstring>, <variant> or <limits>. Including
# them first changes nothing else.
set(STD_PRELUDE ${CMAKE_CURRENT_SOURCE_DIR}/std_prelude.h)
set(AOSP_CXX_FLAGS "$<$<COMPILE_LANGUAGE:CXX>:SHELL:-include ${STD_PRELUDE}>")
if(NOT ANDROID)
    # clang < 19 reports C++23-valid constexpr functions as errors
    list(APPEND AOSP_CXX_FLAGS "$<$<COMPILE_LANGUAGE:CXX>:-Wno-invalid-constexpr>")
endif()

# aosp_lib(<name> [NO_PRELUDE] [extra sources...]): a static library from the generated <name>_SRCS list
function(aosp_lib name)
    set(extra ${ARGN})
    set(flags ${AOSP_CXX_FLAGS})
    list(FIND extra NO_PRELUDE np)
    if(np GREATER -1)
        list(REMOVE_AT extra ${np})
        set(flags)
    endif()
    add_library(${name} STATIC ${${name}_SRCS} ${extra})
    target_include_directories(${name} PRIVATE ${AOSP_INCLUDES})
    target_compile_options(${name} PRIVATE -Wno-unused-parameter -Wno-missing-field-initializers ${flags})
endfunction()

# read-only aconfig flags (Soong generates this header from the release configuration)
execute_process(
    COMMAND ${Python3_EXECUTABLE} -I ${CMAKE_CURRENT_SOURCE_DIR}/flags/gen_flags.py
            ${CMAKE_CURRENT_SOURCE_DIR}/flags/android_content_res.values ${GEN}/flags/android_content_res.h
    RESULT_VARIABLE rc)
if(NOT rc EQUAL 0)
    message(FATAL_ERROR "gen_flags.py failed")
endif()

# ---------------------------------------------------------------- AOSP libraries
# no prelude: posix_strerror_r.cpp undefines _GNU_SOURCE before its first include to get the POSIX strerror_r
aosp_lib(libbase NO_PRELUDE)
target_link_libraries(libbase PRIVATE fmt::fmt)

aosp_lib(liblog)
target_compile_definitions(liblog PRIVATE LIBLOG_LOG_TAG=1006 SNET_EVENT_LOG_TAG=1397638484 ANDROID_DEBUGGABLE=0)

aosp_lib(libcutils)
target_compile_definitions(libcutils PRIVATE _GNU_SOURCE)

aosp_lib(libutils)
target_compile_definitions(libutils PRIVATE ANDROID_UTILS_REF_BASE_DISABLE_IMPLICIT_CONSTRUCTION)
if(ANDROID)
    # misc.cpp would dlopen libutils.so through libvndksupport to forward sysprop changes; not wanted in a
    # stand-alone tool, and Soong's recovery variant compiles it the same way
    set_source_files_properties(${S}/core/libutils/misc.cpp PROPERTIES COMPILE_DEFINITIONS __ANDROID_RECOVERY__)
endif()

aosp_lib(libutils_binder)
target_compile_definitions(libutils_binder PRIVATE ANDROID_UTILS_REF_BASE_DISABLE_IMPLICIT_CONSTRUCTION)

aosp_lib(libziparchive)
target_compile_definitions(libziparchive PRIVATE ZLIB_CONST INCFS_SUPPORT_DISABLED=1)
target_link_libraries(libziparchive PRIVATE apk_zlib)

aosp_lib(libandroidfw_pathutils)
aosp_lib(libincfs_utils)
aosp_lib(libandroidfw)
target_compile_definitions(libandroidfw PRIVATE STATIC_ANDROIDFW_FOR_TOOLS _GNU_SOURCE)
target_include_directories(libandroidfw PRIVATE ${S}/libpng ${CMAKE_BINARY_DIR}/libpng)
target_link_libraries(libandroidfw PRIVATE png_static apk_zlib)

aosp_lib(libbuildversion)

set(PLATFORM_LIBS)
if(ANDROID)
    aosp_lib(libincfs ${S}/incremental_delivery/sysprop/IncrementalProperties.sysprop.cpp
             ${CMAKE_CURRENT_SOURCE_DIR}/android_shims.c)
    set(PLATFORM_LIBS libincfs)
endif()

# ---------------------------------------------------------------- protos (lite runtime, as Android.bp)
set(PROTO_STAGE ${CMAKE_BINARY_DIR}/proto)
set(PROTO_OUT ${GEN}/proto)
file(MAKE_DIRECTORY ${PROTO_STAGE}/frameworks/base/tools/aapt2 ${PROTO_OUT})
set(AAPT2_PB_SRCS)
foreach(p ${libaapt2_PROTOS})
    get_filename_component(n ${p} NAME_WE)
    configure_file(${p} ${PROTO_STAGE}/frameworks/base/tools/aapt2/${n}.proto COPYONLY)
endforeach()
foreach(p ${libaapt2_PROTOS})
    get_filename_component(n ${p} NAME_WE)
    set(cc ${PROTO_OUT}/frameworks/base/tools/aapt2/${n}.pb.cc)
    add_custom_command(OUTPUT ${cc} ${PROTO_OUT}/frameworks/base/tools/aapt2/${n}.pb.h
        COMMAND ${PROTOC} --proto_path=${PROTO_STAGE} --proto_path=${PROTO_STAGE}/frameworks/base/tools/aapt2
                --cpp_out=lite:${PROTO_OUT} ${PROTO_STAGE}/frameworks/base/tools/aapt2/${n}.proto
        DEPENDS ${PROTO_STAGE}/frameworks/base/tools/aapt2/${n}.proto
        COMMENT "protoc ${n}.proto")
    list(APPEND AAPT2_PB_SRCS ${cc})
endforeach()

# ---------------------------------------------------------------- AAPT2
set(AAPT2_FLAGS -Wno-unused-parameter -Wno-missing-field-initializers -fno-exceptions -fno-rtti
                -Wno-deprecated-declarations)
add_library(libaapt2 STATIC ${libaapt2_SRCS} ${AAPT2_PB_SRCS})
target_include_directories(libaapt2 PUBLIC ${S}/base/tools/aapt2 ${PROTO_OUT} ${PROTO_OUT}/frameworks/base/tools/aapt2
                           ${S}/protobuf/third_party/utf8_range
                           PRIVATE ${AOSP_INCLUDES} ${S}/libpng ${CMAKE_BINARY_DIR}/libpng)
target_compile_options(libaapt2 PRIVATE ${AAPT2_FLAGS} ${AOSP_CXX_FLAGS})
target_link_libraries(libaapt2 PUBLIC protobuf::libprotobuf-lite expat::expat png_static)

add_executable(aapt2 ${aapt2_SRCS})
target_include_directories(aapt2 PRIVATE ${AOSP_INCLUDES} ${S}/libpng ${CMAKE_BINARY_DIR}/libpng)
target_compile_options(aapt2 PRIVATE ${AAPT2_FLAGS} ${AOSP_CXX_FLAGS})
target_link_options(aapt2 PRIVATE -Wl,--gc-sections -Wl,-Map=${CMAKE_BINARY_DIR}/aapt2.map)
if(ANDROID)
    # fully static: runs from the app's native library directory with nothing else
    target_link_options(aapt2 PRIVATE -static)
    # 16 KiB pages (Android 15+ devices may use them); NDK r28+ defaults to this, stated here for the record
    target_link_options(aapt2 PRIVATE -Wl,-z,max-page-size=16384)
endif()
target_link_libraries(aapt2 PRIVATE
    -Wl,--start-group
    libaapt2 libandroidfw libandroidfw_pathutils libincfs_utils ${PLATFORM_LIBS} libziparchive libutils
    libutils_binder libcutils libbase liblog libbuildversion
    -Wl,--end-group
    protobuf::libprotobuf-lite expat::expat png_static apk_zlib fmt::fmt)
if(NOT ANDROID)
    target_link_libraries(aapt2 PRIVATE pthread)
endif()
