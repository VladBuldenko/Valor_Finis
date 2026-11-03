# Device Matrix and Pinned OS Floors (QA-0)

Date: 2026-11-03 (verification date for every statement below). Task: QA-0, branch `docs/VF-QA-DEVICE-MATRIX`.
Basis: `main` @ `8bb98fb4ae07602825a9f44b8ada5561947ef913` (Expo SDK 57, `expo` 57.0.20, React Native 0.86.3).
Decision: Q12 in [mvp-decision-record.md](mvp-decision-record.md). Gate: BR-5 in [mvp-readiness-gates.md](mvp-readiness-gates.md).
Acceptance rows: [qa-device-acceptance-template.md](qa-device-acceptance-template.md). Evidence rules:
[qa-evidence-and-staging-isolation.md](qa-evidence-and-staging-isolation.md).

**Status: the floors are pinned and verified. No device, emulator or staging run has happened.** Every device slot below
that is not an installed simulator is `TBD` or `BLOCKED`. Nothing in this file is a test result. The owner has not yet
approved any physical reference device.

## 1. Pinned floors

| Platform | Pinned minimum | Binding source | Status |
|---|---|---|---|
| iOS | **16.4** | Expo SDK 57 (`expo-modules-core` and `expo` podspecs; Expo documentation) | Verified from three independent sources (section 2) |
| Android | **API 24 (Android 7.0)** | React Native 0.86.3 and Expo SDK 57 agree | Verified from three independent sources (section 2) |

Rule used: when minimums conflict, the **highest applicable minimum** is the floor. React Native 0.86.3 alone would allow a
lower iOS version, but the app is built with Expo SDK 57, whose native modules require 16.4, so a lower iOS version cannot
install or build the app. The earlier lower iOS value is therefore **not supported** and must not be tested as a floor.

## 2. Verification evidence

### 2.1 iOS

| # | Source | What it says | How it was checked (2026-11-03) |
|---|---|---|---|
| 1 | Expo SDK 57 documentation, `https://docs.expo.dev/versions/v57.0.0/` | Minimum iOS 16.4+, minimum Xcode 26.4+; table row `\| 57.0.0 \| 7+ \| 36 \| 36 \| 16.4+ \| 26.4+ \|` (Android minimum, compileSdk, targetSdk, iOS minimum, Xcode minimum); React Native 0.86 | Page fetched and the row read; the fetch tool summarised the page, so the row was read from the tool's quotation |
| 2 | Installed `expo-modules-core` 57.0.16 and `expo` 57.0.20 | `ExpoModulesCore.podspec:54` and `Expo.podspec:39` declare iOS `16.4`; 24 podspecs under `node_modules` declare `16.4` | Read from the installed packages of a clean `npm ci` of this lockfile (versions equal `package-lock.json`) |
| 3 | Generated native project | `Podfile` line 25: `platform :ios, podfile_properties['ios.deploymentTarget'] \|\| '16.4'`; four `IPHONEOS_DEPLOYMENT_TARGET = 16.4` entries in the generated Xcode project; `Podfile.properties.json` sets no deployment target | `expo prebuild --no-install --platform all` run in an **isolated scratch copy** outside the repository; nothing generated was kept or committed |

Lower iOS values found in installed packages and why they do not set the floor:

| Package | Declared iOS minimum | Binding? |
|---|---|---|
| React Native 0.86.3 (`react-native/scripts/cocoapods/helpers.rb`), `hermes-engine`, `react-native-screens` 4.26.2 | 15.1 | No: lower than 16.4 |
| `react-native-reanimated` 4.5.1, `react-native-worklets` 0.10.1 | 13.4 | No |
| `react-native-safe-area-context` | 12.4 | No |
| `@react-native-async-storage/async-storage` 2.2.0 | 9.0 | No |

### 2.2 Android

| # | Source | What it says | How it was checked (2026-11-03) |
|---|---|---|---|
| 1 | Expo SDK 57 documentation (same page) | Minimum Android 7+, compileSdk 36, targetSdk 36 | As above |
| 2 | Installed `react-native` 0.86.3, `gradle/libs.versions.toml` | `minSdk = "24"`, `targetSdk = "36"`, `compileSdk = "36"`, `buildTools = "36.0.0"`, `ndkVersion = "27.1.12297006"` | Read from the installed package |
| 3 | Installed `expo-modules-core` 57.0.16, `android/ExpoModulesCorePlugin.gradle:65-69` and the Gradle plugin | Defaults `minSdkVersion` 24, `compileSdkVersion` 36, `targetSdkVersion` 36 | Read from the installed package |

The generated Android project (scratch prebuild above) reads `minSdkVersion`, `targetSdkVersion` and `compileSdkVersion`
from `rootProject.ext`. Gradle resolves those values at build time. **They were not evaluated here** because the machine has
no JDK and no Android SDK (finding F-04). The three sources agree, so the pin is well supported, but an actual Android build is
the final confirmation and remains outstanding.

### 2.3 Toolchain minimums that follow from the pin

| Tool | Minimum | Source | Installed on the verifying machine |
|---|---|---|---|
| Xcode | 26.4+ (Expo docs); 16.1 (React Native helper) | highest applies: 26.4 | 26.3 (build 17C529): **below the documented minimum** (F-02) |
| Node.js | 22.13.0 | `engines` in `apps/mobile/package.json`, `.nvmrc` | 22.23.2 (npm 10.9.8) |
| Android SDK platform | 36, build tools 36.0.0, NDK 27.1.12297006 | React Native `libs.versions.toml` | None installed (F-04) |

## 3. QA-0 findings

| ID | Finding | Evidence | Affected statements | Effect and action |
|---|---|---|---|---|
| F-01 | **The roadmap-era iOS floor is wrong for Expo SDK 57.** Q12 took 15.1 from React Native alone and said a higher Expo floor replaces it. Expo SDK 57 requires 16.4. (QA-0 exception: this row quotes the superseded value 15.1 on purpose.) | Section 2.1 | `mvp-decision-record.md` Q12 (line 31); `mvp-readiness-gates.md` BR-5 (line 42); `mvp-ops03-and-staging-prerequisites.md` section 2.1 row 10 (line 61); `mvp-qa-readiness.md` v1.1 addendum (line 119); `mvp-engineering-gap-matrix.md` GAP-22 (line 36). Line numbers are those of base `8bb98fb` | Floor pinned to iOS 16.4. Each of the five statements now carries a "QA-0 superseded" note; the original wording is kept as history. Q12's own replacement rule authorizes this; the owner is asked to acknowledge (OD-3). Android API 24 is unchanged. No Expo, SDK or production config was modified |
| F-02 | Installed Xcode 26.3 is below the documented Expo SDK 57 minimum of 26.4+ | `xcodebuild -version`: Xcode 26.3 (17C529) | none (new) | Native iOS builds from this machine are outside Expo's documented support until Xcode is updated (OD-5). Not tested; not claimed to fail |
| F-03 | No iOS 16.4 simulator runtime is installed; only iOS 26.3 (26.3.1, 23D8133) | `xcrun simctl list runtimes` | none (new) | The minimum-iOS simulator slot is BLOCKED. Whether a 16.4 runtime can be installed and run on this macOS and Xcode is unverified (OD-9) |
| F-04 | No Android toolchain: no Android SDK, `adb`, `emulator`, `avdmanager`, `sdkmanager`, and no JDK | tool lookups and `java -version` on 2026-11-03 | none (new) | The API 24 emulator slot and the current-Android slot are BLOCKED. Android has never been run (matches `mvp-qa-readiness.md` row 10: Android UNKNOWN) |
| F-05 | CocoaPods (`pod`) is not installed | tool lookup | none (new) | A local native iOS build cannot complete. Not needed for Expo Go runs |
| F-06 | `app.json` defines no `ios.bundleIdentifier` and no `android.package`; there is no `eas.json` and no `expo-dev-client`. The prebuild dry run derived placeholder identifiers from the local machine | `apps/mobile/app.json`; `ls`; scratch prebuild | none (new) | A signed/internal device build is not currently possible. Stable identifiers are a production app-config change, outside QA-0 (OD-4) |
| F-07 | The URL scheme is the generic `mobile` (also in the generated manifest and `Info.plist`) | `app.json` `expo.scheme`; scratch prebuild | MF-4 prerequisite B9 | Recovery and registration deep links (J19, J20) need an app-unique scheme. Already tracked under MF-4 |
| F-08 | Physical-device acceptance so far has been over Expo LAN with Expo Go. Expo Go is not the shipped binary and its own OS support is set by Expo Go, not by this app | `CLAUDE.md` (LAN is the known reliable mode); no `eas.json` | none (new) | Whether Expo Go runs may count for BR-5, or a standalone internal build is required, is an owner decision (OD-4). Performance (QA-3) is never measured in Expo Go |

No physical device model or OS version is recorded anywhere in the repository, so none is claimed here. Earlier
physical checks (for example VF-020C3) were user-confirmed without a recorded model.

## 4. Matrix

"Counts for BR-5" separates **minimum-OS compatibility** (floor runs on a simulator or emulator) from **physical-device
acceptance** (BR-5's 40 rows). A simulator or emulator result never becomes a physical-device `PASS`.

| Slot | Platform | Target | Kind | Counts for BR-5 | Model and OS | Status |
|---|---|---|---|---|---|---|
| S-IOS-MIN | iOS | Minimum supported OS | Simulator | Floor compatibility only | iPhone simulator on iOS 16.4: device type TBD | **BLOCKED** (F-02, F-03) |
| S-AND-MIN | Android | Minimum supported OS | Emulator | Floor compatibility only | Android 7.0 (API 24) image: device profile TBD | **BLOCKED** (F-04) |
| S-IOS-CUR | iOS | Current stable | Simulator | Supporting only | iOS 26.3 runtime is installed here (iPhone 17, iPhone 17 Pro, iPhone 17 Pro Max, iPhone Air, iPhone 16e and iPads). "Current stable" is re-confirmed on the day of each run | AVAILABLE here; not yet run |
| S-AND-CUR | Android | Current stable | Emulator | Supporting only | Latest stable Android: version TBD on the run date | **BLOCKED** (F-04) |
| P-IOS-1 | iOS | Reference device | **Physical** | **Yes (J01–J20)** | TBD: model and OS to be approved by the owner | **TBD** (OD-1) |
| P-AND-1 | Android | Reference device | **Physical** | **Yes (J01–J20)** | TBD: model and OS to be approved by the owner | **TBD** (OD-2) |
| P-IOS-2 | iOS | Optional second device (older or smaller) | Physical | Supporting | TBD | TBD |
| P-AND-2 | Android | Optional second device (older or lower-spec) | Physical | Supporting | TBD | TBD |

### 4.1 Floor compatibility smoke set (simulator or emulator at the pinned floor)

Journeys J01, J02, J03, J04, J07, J12 and J15 (Inbox open), plus procedures SP-05 and SP-16, run against staging. It
proves the app installs, signs in and renders money correctly on the oldest supported OS. Results are kept in the run
directory as `artifacts/floor-compat.md` with the same evidence and redaction rules. **The validator does not check this
file** (it is not part of the 40 physical rows); the release reviewer reads it.

### 4.2 Physical reference devices (owner approval required)

The owner must approve the actual devices **before QA-3** (performance baseline), because QA-3 uses "the lowest-specification
physical device of the owner-approved matrix" on each platform.

| Slot | Model | Exact OS version | Physical | Approved by | Approved on | Status |
|---|---|---|---|---|---|---|
| P-IOS-1 | TBD | TBD | yes | — | — | NOT APPROVED |
| P-AND-1 | TBD | TBD | yes | — | — | NOT APPROVED |

Selection criteria for the owner (a recommendation, not a decision): the device must run the pinned floor or newer; the
approved device should be the one the owner is willing to treat as the lowest-specification reference; one device on a
current OS and one near the floor gives the widest coverage; the exact model and OS are recorded in every row.

## 5. Test build record (recorded for every run)

| Item | Rule |
|---|---|
| Build type | `expo-go` (Expo CLI over LAN, the known reliable mode), `development-build` (not available: no `expo-dev-client`), or `internal-release` (not available: no `eas.json`, no bundle identifiers; F-06). Today only `expo-go` can be used |
| Build channel | `local-lan` for Expo Go; the channel name once an EAS channel exists |
| Commit SHA | The full 40-character `git rev-parse HEAD` of a **clean** working tree (`git status --short` empty) at the moment the bundle is served or built. A dirty tree makes the build identifier invalid |
| Installation method | Recorded in words: for example "Expo Go from the store, QR scan over LAN". Never include a URL, IP or port |
| App version | `expo.version` from `app.json` at that commit (currently `1.0.0`) |
| Backend environment | A staging identifier that is `ACTIVE` in [qa-evidence/staging-register.md](qa-evidence/staging-register.md), the backend commit SHA, and the migration head of that commit; the live database revision only with an assertion record |
| Environment variables | The three `EXPO_PUBLIC_*` names in `apps/mobile/src/config/env.ts` point only at staging, proved by the fingerprint check (isolation document, section 3) |
| Not allowed | A production endpoint in any physical-device build; performance claims from Expo Go; a `PASS` from a dirty tree |

## 6. Network and accessibility configurations

| ID | Network configuration | Used by |
|---|---|---|
| NW-W | Wi-Fi, 20 Mbps or more, round trip to staging 50 ms or less (profile W of BR-9) | default for all rows |
| NW-C | Throttled to 9 Mbps down, 3 Mbps up, 100 ms round trip (profile C of BR-9) | QA-3 and constrained spot checks |
| NW-OFF | Airplane mode or no connectivity | SP-02, SP-16 |
| NW-DROP | Connection dropped right after a request is sent | SP-02, SP-08 |
| NW-STALL | A request that never answers (operator-run delaying proxy) | SP-02, SP-04 |
| NW-BLOCK | Network that blocks the staging origin | SP-06 |

| ID | Accessibility configuration | Used by |
|---|---|---|
| AX-0 | Defaults: no screen reader, default text size, light mode | default for all rows |
| AX-DK | Dark mode (the app follows the system setting) | J01–J04 once in each mode |
| AX-SR | VoiceOver on iOS, TalkBack on Android | SP-17, SP-13 |
| AX-LT | Largest text size (iOS) / largest font and display size (Android) | SP-17 |
| AX-RM | Reduce motion (iOS) / remove animations (Android) | SP-17 |
| AX-HC | Bold text or high contrast | SP-17 |

## 7. Recorded exceptions for the stale-floor check

The validator fails any Markdown line that names an iOS version below 16.4 or an Android API level below 24 unless the line
carries the marker "QA-0 superseded" or "QA-0 exception". The recorded exceptions are the five statements listed in F-01
(each annotated in place) and this file's own references to the superseded value. A new exception needs the same marker and
a reason on the same line.

## 8. Owner decisions and open items

| ID | Decision or input needed | Blocks |
|---|---|---|
| OD-1 | Approve the physical iPhone (model, exact OS) | QA-3, all iOS rows |
| OD-2 | Approve the physical Android phone (model, exact OS) | QA-3, all Android rows |
| OD-3 | Acknowledge the iOS floor change to 16.4 (Q12 already allows it) | none; recorded for audit |
| OD-4 | Decide whether Expo Go runs may count for BR-5 or an internal release build is required; if required, decide the bundle identifiers and EAS setup (a separate app-config task) | internal build, QA-3, J19/J20 deep links |
| OD-5 | Update Xcode to 26.4 or later, or accept Expo Go only for iOS until then | native iOS builds |
| OD-6 | Provide an Android toolchain (workstation or CI) able to run an API 24 emulator | S-AND-MIN, S-AND-CUR |
| OD-7 | Provide staging inputs and fingerprints (QA-1) | every run |
| OD-8 | Decide whether to wire `tools/qa/validate-qa-evidence.mjs` into CI | nothing; optional |
| OD-9 | Confirm that an iOS 16.4 simulator runtime can be installed on the current macOS and Xcode (Apple's availability is unverified) | S-IOS-MIN |

## 9. Verifying machine (2026-11-03)

macOS (Darwin 24.6.0); Xcode 26.3 (17C529); one simulator runtime, iOS 26.3 (26.3.1, 23D8133); Node v22.23.2, npm 10.9.8; no
CocoaPods, no JDK, no Android SDK. `expo prebuild` was run only in a scratch copy outside the repository.
