# APK Builder 005 — Stage 0 toolchain feasibility

This repository belongs to the APK Builder project (an offline Android APK compiler that runs on a Samsung
Galaxy S25). It holds **Stage 0 feasibility work only**: it builds and checks components that a future
APK Builder 005 might use, and prepares the inputs of the disposable phone probe (Stage 1). Nothing here is
part of an installed APK Builder, and nothing here counts as tested on a phone until the owner has tested it.

Approved by the owner on 16 November 2026: D-00 (download and investigate open-source components),
D-01 option A (one disposable, separately installed test APK), D-03 option A (AAPT2 built from official AOSP
source with GitHub Actions), D-04 option A (framework resource table generated from pinned AOSP source).

## Workflows

Each workflow publishes its outputs as a pre-release named `<workflow>-run-<n>` with `SHA256SUMS.txt` and
`PROVENANCE.json` (commit, run, pinned inputs, job results).

| Workflow | Source (official only) | Output |
| --- | --- | --- |
| `maven` | Google Maven, Maven Central | the Compose/AndroidX/Material candidate set and its full dependency closure, every file checked against the published checksum; licences, class-file versions, `minCompileSdk`, `minSdk`; R8 (D8) |
| `aapt2-src` | android.googlesource.com at `android-17.0.0_r1`, fetched with the recipe's `get_source.py` ([lzhiyong/android-sdk-tools](https://github.com/lzhiyong/android-sdk-tools), Apache-2.0, pinned commit) | a source snapshot of every repository AAPT2 is built from (no `.git`), `SOURCES.txt` with each repository's commit, and a report of recipe paths that no longer exist at this tag |
| `aapt2` | the pinned source snapshot (SHA-256 in `pins/stage0.env`); NDK from Google's SDK repository; `frameworks/base` `core/res` and `build/release` at the tag | AAPT2 for Linux x86_64 and a fully static AAPT2 for Android ARM64 (this repository's CMake build in `aapt2/`, source lists generated from the tag's own `Android.bp` files), link map and binary checks, the framework resource table with every public ID checked, a resource test project linked against it, and the same table and link repeated by the ARM64 binary on an ARM64 runner |
| `stubs` | AOSP platform manifest, `frameworks/base`, `libcore`, ICU, Conscrypt, `packages/modules/*`, `packages/providers/*` at `android-17.0.0_r1` | merged public API signature file, the collected signature files themselves, and compile-time stubs made by `tools/StubGen.java` |

The Android SDK's own `android.jar` is downloaded only to **compare** results with it. It is never
published, and nothing from it is copied into an output.

## Directories

* `aapt2/` – CMake build of AAPT2 and the libraries it links (see the header of `aapt2/CMakeLists.txt` for every
  deliberate difference from the upstream device build), host `protoc` wrapper, aconfig flag header generator,
  build-number stamping and binary checks.
* `probe/prepare_assets.py` – makes the input files and desktop reference results of the phone probe.
* `samples/` – `res-smoke` (resource test project), `compose-hello` (Compose + Material 3 sample),
  `lambda-test` (Java 8 desugaring sample).
* `scripts/` – the workflow steps; `pins/` – pinned inputs; `tools/` – `StubGen.java` (from APK Builder 004,
  extended to read signature format 6.0 in Java style) and `detjar.py` (unchanged from 004).

## Licences

The scripts in this repository are the owner's. Every third-party component keeps its own licence:
AOSP sources and AndroidX libraries Apache-2.0 (`licenses/Apache-2.0.txt`), R8 BSD-3-Clause, the build recipe
Apache-2.0. The licences found for each library are listed in `closure.json` of each `maven` run; the AOSP
repositories in the source snapshot keep their own LICENSE/NOTICE files.
