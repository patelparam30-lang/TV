# Native Home control

This one-shot development helper is scoped to Nathan's Frame and firmware 2130.0. It does not run inside CleanFrame or remain active on the TV. It uses the existing SDB developer connection and the published package-name command workaround to execute as SDK UID 901. It does not request root or change security policy.

`Control.cs` exposes read-only query, guarded apply, and exact-value restore through native Home and vconf APIs. It refuses other firmware, root, changed original values, or an ineligible/missing app. Apply failures attempt immediate restore. The baseline and compiled tools remain in ignored `.local/native-home/`.

From the project root:

```sh
python3 scripts/native-home/run.py query
python3 scripts/native-home/run.py restore
```

The existing private `original.json` is the tested rollback baseline. Do not overwrite it with the applied state. The runner re-stages the helper and baseline each time. The query/apply/restore/inspect shell source is retained beside the runner. It needs the compiled output in `.local/native-home/out/`; build with the private verified Microsoft SDK when the C# source changes. No local address, device identifier, compiled binary or signing secret belongs in this source folder.

Even query/inspect stages temporary helper files on the device. These are device operations, not offline repository checks. A clone without the private baseline, SDK and compiled output cannot perform the tested rollback. Preserve the local recovery folder separately; GitHub is a source backup only.

The implementation was reviewed against the [published S90D native Home work](https://github.com/splitcipher/couchroot/blob/83906b468836869933012da03a4018fb339462b3/docs/devices/s90d/README.md). This Frame's native query, apply/restore/reapply and physical Home-from-Netflix test were checked independently. Source review does not replace device testing after future firmware changes.

## Independent compatibility inspection

`inspect-personal.py` is a separate, read-only first step for an owner's Samsung
Tizen 9.0 ARMv7 TV. Run it on the computer with SDB access, passing `--host` and
the SDK-generated `--app-id`. It checks capabilities and the installed app before
staging a temporary shell probe. It uses the same reviewed SDK command transport
as the reference runner, with a bounded callback on the computer's local network.
It reads the firmware, SDK user, native library paths, .NET runtime directories,
and typed Home preferences. It neither installs a resident helper nor writes
Home/startup settings. Python may need local-network access through the computer's
firewall. Reports default to `~/ParamHome-recovery` and must remain private.

An inspection is **not a recovery baseline**: it does not read the native Home
operation or establish boot eligibility. A successful result does not establish
that the reference apply/restore helper supports the new model. Review those
details and prepare an exact-value recovery snapshot before any native writes.
The reference `run.py` and `Control.cs` guards remain unchanged.

## Owner-specific helper and recovery bundle

After reviewing a complete inspection, use `personal-home.py prepare` on the
owner's computer with `--host`, `--app-id`, and `--inspection` pointing to the saved
report. `--download-sdk` permits downloading Microsoft's SHA-512-verified .NET
6.0.428 build SDK into the private recovery folder (Apple Silicon macOS or Linux
x64). No system-wide SDK installation or signing credentials are needed. This
compiler targets the TV's observed .NET 6 runtime. The source project is
`PersonalControl.csproj`; compilation and runtime outputs stay private.

Prepare stages and runs a **read-only** native query. The helper requires the
inspected firmware/model pair, 32-bit SDK UID 901, a registered target app and
native boot eligibility. It reads the actual main Home operation and all five
typed preferences. Prepare compares these preferences with the earlier
inspection before exclusively creating `original.json`. Existing originals are
never replaced. It saves the source, compiled helper, owner configuration and
SHA-256 integrity manifest under `~/ParamHome-recovery`, and creates a separate
sibling recovery backup. Neither prepare nor query changes Home/startup.

After reviewing the original snapshot and verifying visible Samsung Home access,
the copied recovery runner supports:

```sh
python3 "$HOME/ParamHome-recovery/personal-home.py" query
python3 "$HOME/ParamHome-recovery/personal-home.py" apply
python3 "$HOME/ParamHome-recovery/personal-home.py" restore
```

Apply requires the exact original native assignment and typed settings. It sets
the native Home operation and `home_appid` to the owner's target and enables Home
autostart. It preserves first-screen type and reports the firmware's derived
startup/backup fields without assuming that a readback proves startup behaviour.
Every explicit write is read back. Failure attempts an exact-value restore and
reports restore failure separately. Explicit restore verifies all original
values, does not require the target launcher to remain installed or boot eligible,
and still enforces the firmware/model and SDK-user guards. A changed Home
assignment outside the original/custom pair stops writes for review.

All operations re-stage their dependencies under unique temporary filenames;
restore does not depend on previous device temporary files. Before writes, the
runner checks the complete local recovery manifest. `--host` and `--sdb` can
override changed network/tool paths without modifying saved originals. If an
apply result is incomplete, stop and query; do not apply repeatedly. No command
automatically restarts the TV, launches an app, or performs a restore/reapply
cycle. Confirm physical Home after each intentional transition and test normal
power-on separately. Keep both recovery folders outside the downloaded source
tree, and preserve them before updates or removal.

Offline checks: `python3 scripts/check-personal-home.py`. These test inspection
parsing, immutable baselines, bundle integrity and loopback callback handling;
they do not establish physical-TV compatibility or power-on behaviour.
