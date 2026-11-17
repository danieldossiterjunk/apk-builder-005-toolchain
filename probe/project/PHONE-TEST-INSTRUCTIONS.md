# APK Builder 005 feasibility probe — phone test

This is a small, throw-away test app. It checks, on your Galaxy S25, the three things APK Builder 005 would
need and that cannot be proven on a desktop:

* **P1 – Compose compiler plugin**: APK Builder 004's own Kotlin compiler (the same file, unchanged) compiles a
  small Jetpack Compose + Material 3 screen with the Compose compiler plugin loaded into it.
* **P2 – D8**: Google's D8 (the tool that turns Java/Kotlin classes into Android DEX code) runs inside the app,
  converts the compiled screen, converts and runs a Java 8 test, merges everything with the AndroidX/Compose
  libraries, and then every class is loaded to see whether Android accepts it.
* **P3 – AAPT2**: the resource compiler built for this test from Android 17's official source runs from the
  app, compiles and links resources against the Android 17 framework table, compares that table with your
  phone's own framework resources (read only, for comparison), and links the real AndroidX/Material library
  resources.

It is a **separate app** ("APK Builder 005 Probe", package `org.apkbuilder.probe005`). It does not open,
change or share anything with APK Builder 001–004, their signing keys or their data. It asks for no
permissions (no internet, no storage); the report leaves the app only when you save it with Android's file
picker or copy it.

## Steps

1. **Copy the project** folder `APK_Builder_005_Probe` to your phone the same way you copied the APK Builder
   004 project, and open it in Code on the Go.
2. **Build** a debug APK in Code on the Go (offline, exactly as for Build 004). The project uses the same
   Gradle set-up as Build 004 (AGP 9.3.1, compile SDK 36). The APK is large (about 140 MB) because the tools
   under test are inside it; the build can take longer than Build 004's. Keep about **1 GB free** on the phone
   (the APK, plus about 400 MB the probe unpacks into its own storage while testing).
3. **Install** it from Code on the Go and allow the installation as usual. It installs **next to** your APK
   Builder apps and does not replace any of them.
4. **Open** "APK Builder 005 Probe" and press **Run all**. Keep the screen on and the app in front.
   The first run copies about 140 MB of test files into the app's private storage, then runs P1, P2 and P3.
   Expect several minutes; the log on screen shows each step. The buttons P1/P2/P3 run one test alone if you
   need to repeat one.
5. When it says **Finished**, press **Save report** and save the JSON file somewhere you can find it (or press
   **Copy report** and paste it into a file).
6. **Send me the report** together with what you saw:
   * whether Code on the Go built and installed it without errors (if not, the error text);
   * whether the app crashed or closed at any point (and at which step);
   * roughly how long "Run all" took.

That is all. Nothing in the report is a pass or fail by itself: each check says **CHECK OK** or **CHECK
FAILED**, and you decide what counts as passed. I will not mark any phone test as passed until you have run it
and sent the result.

## If something goes wrong

* **App closes during P1 or P2** (out of memory is the most likely cause): reopen it, press only **P3 AAPT2**,
  save that report, then try **P1 Compose** and **P2 D8** separately and save a report after each.
* **"Running" never ends** (more than 20 minutes): force-stop the app from Android's app settings, reopen it
  and run the tests one at a time as above.
* **Code on the Go cannot build it**: send me the build output. Nothing on the phone has changed at that point.

## Afterwards

The probe can be uninstalled at any time (long-press the icon, Uninstall). That removes its test files too.
It is not needed for anything else.
