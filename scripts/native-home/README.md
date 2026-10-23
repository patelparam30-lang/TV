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
