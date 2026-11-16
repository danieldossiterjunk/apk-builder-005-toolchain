# APK Builder 005 — Stage 0 toolchain feasibility

This repository belongs to the APK Builder project (an offline Android APK compiler that runs on a Samsung
Galaxy S25). It holds **Stage 0 feasibility work only**: it builds and checks components that a future
APK Builder 005 might use. Nothing here is part of an installed APK Builder, and nothing here has been
tested on a phone.

Approved by the owner on 16 November 2026: D-00 (download and investigate open-source components),
D-03 option A (AAPT2 built from official AOSP source with GitHub Actions), D-04 option A (framework
resource table generated from pinned AOSP source).

## What the `stage0` workflow does

| Job | Source (official only) | Output |
| --- | --- | --- |
| `maven` | Google Maven, Maven Central | the Compose/AndroidX/Material candidate set and its full dependency closure, every file checked against the published checksum; licences, class-file versions, `minCompileSdk`, `minSdk`; R8 (D8) and ASM |
| `aapt2` | android.googlesource.com at three tags; build recipe [lzhiyong/android-sdk-tools](https://github.com/lzhiyong/android-sdk-tools) (Apache-2.0) at a pinned commit; NDK from Google's SDK repository | AAPT2 for Linux x86_64 and a static AAPT2 for Android ARM64, with source commits, readelf output and link map |
| `framework` | `platform/frameworks/base` `core/res` at `android-17.0.0_r1` | `framework-res.apk` and the stripped `android-framework-table.apk` (manifest + `resources.arsc`), every public resource ID checked, a smoke-test project linked against it |
| `arm64-smoke` | — | the Android ARM64 AAPT2 run on an ARM64 Linux runner against the same smoke test |
| `stubs` | AOSP platform manifest, `frameworks/base`, `libcore`, ICU, Conscrypt, `packages/modules/*` at `android-17.0.0_r1` | merged public API signature file and compile-time stubs made by APK Builder's `StubGen` |
| `publish` | — | a pre-release with every output, `SHA256SUMS.txt` and `PROVENANCE.json` |

The Android SDK's own `android.jar` is downloaded only to **compare** results with it. It is never
published, and nothing from it is copied into an output.

## Inputs

`pins/stage0.env` and the `env:` block of the workflow (AOSP tag, recipe commit, NDK version),
`pins/maven-roots.txt` (library candidates), `samples/res-smoke/` (resource smoke test).
`tools/StubGen.java` and `tools/detjar.py` are copied unchanged from APK Builder 004.

## Licences

The scripts in this repository are the owner's. Every third-party component keeps its own licence:
AOSP sources and AndroidX libraries Apache-2.0 (`licenses/Apache-2.0.txt`), R8 and ASM BSD-3-Clause, the
build recipe Apache-2.0. The licences found for each library are listed in `closure.json` of each run.
