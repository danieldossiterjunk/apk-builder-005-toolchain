# APK Builder 005 feasibility probe (Stage 1, disposable)

A Code on the Go project that builds one small Android app, **APK Builder 005 Probe**
(`org.apkbuilder.probe005`, version 0.1.0). It runs the three Stage 1 phone tests (P1 Compose compiler plugin,
P2 D8, P3 AAPT2) and writes a JSON report. How to build and run it: `PHONE-TEST-INSTRUCTIONS.md`.

It is not part of APK Builder and is not needed after the tests. It does not touch APK Builder 001–004, their
signing keys or their data, asks for no permissions, and has no services, receivers or providers.

## Layout

| Path | What |
| --- | --- |
| `app/src/main/java/org/apkbuilder/probe005/` | the app: `MainActivity` (one screen), `Probe` (the tests), helpers for JSON, files, class/DEX reading and processes |
| `app/src/main/assets/probe/` | the inputs of the tests and `MANIFEST.json` (SHA-256 and size of every input, and the desktop reference results the phone's results are compared with) |
| `app/src/main/jniLibs/arm64-v8a/libprobe_aapt2.so` | AAPT2 for Android ARM64, a static program (named `.so` so that Android installs it where an app may start it) |
| `gradle/`, `gradlew`, `*.gradle`, `gradle.properties` | the same Gradle set-up as APK Builder 004 |

## Where the inputs come from

Everything in `assets/probe` and `jniLibs` was made by `probe/prepare_assets.py` of the toolchain repository
`danieldossiterjunk/apk-builder-005-toolchain` from:

* APK Builder 004's own `kotlin-compiler-dex.zip` and `kotlin-stdlib-2.4.0.jar` (byte-identical copies);
* the official Kotlin 2.4.0 distribution (Compose compiler plugin, converted to DEX by D8);
* D8/R8 9.5.32 and the Compose/Material 3/AndroidX libraries from Google Maven / Maven Central (`maven-run-6`);
* API 37 stubs generated from AOSP `android-17.0.0_r1` (`stubs-run-4`);
* AAPT2 and the framework resource table built from AOSP `android-17.0.0_r1` by CI (`aapt2-run-12`).

Each run's `PROVENANCE.json` and `SHA256SUMS.txt` are in `evidence/ci/` of the delivery package. Third-party files
keep their own licences (Apache-2.0 for Kotlin, AOSP and the AndroidX libraries; BSD-3-Clause for R8 with the
notices inside its JAR).
