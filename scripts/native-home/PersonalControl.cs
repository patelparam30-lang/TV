using System;
using System.Collections.Generic;
using System.IO;
using System.Runtime.InteropServices;
using System.Text.Json;
using System.Text.RegularExpressions;

// One-shot SDK-user tool. Configuration and originals belong to the owner.
class PersonalControl {
    const string Operation = "http://tizen.org/appcontrol/operation/main";
    const string AutoKey = "db/menu/smart_hub/ontvsetting/auto_start";
    static readonly string[] Keys = { "db/appfw/home_appid", "db/appfw/startup_appid",
        "db/appfw/booting_appid_backup", "db/first_screen/type" };

    public class Device {
        public string AppId { get; set; }
        public string Firmware { get; set; }
        public string Model { get; set; }
    }
    public class Snapshot {
        public Device Device { get; set; }
        public string Home { get; set; }
        public Dictionary<string, string> Strings { get; set; }
        public int Autostart { get; set; }
        public uint Uid { get; set; }
        public int BootSupported { get; set; }
    }

    [DllImport("libbundle.so.0")] static extern IntPtr bundle_create();
    [DllImport("libbundle.so.0")] static extern void bundle_free(IntPtr bundle);
    [DllImport("libaul.so.0")] static extern int aul_svc_set_operation(IntPtr bundle, string operation);
    [DllImport("libaul.so.0")] static extern int aul_get_default_app(IntPtr bundle, out IntPtr app);
    [DllImport("libapp-context-manager-common.so")]
    static extern byte util_is_appbooting_supported_webapp_byappid(string app);
    [DllImport("libcapi-appfw-app-operation-tv.so.0")]
    static extern int app_operation_set_current_app(string operation, string app);
    [DllImport("libvconf.so.0")] static extern int vconf_set_str(string key, string value);
    [DllImport("libvconf.so.0")] static extern IntPtr vconf_get_str(string key);
    [DllImport("libvconf.so.0")] static extern int vconf_set_int(string key, int value);
    [DllImport("libvconf.so.0")] static extern int vconf_get_int(string key, out int value);
    [DllImport("libc")] static extern uint getuid();
    [DllImport("libc")] static extern void free(IntPtr ptr);

    static void Require(bool condition, string message) {
        if (!condition) throw new Exception(message);
    }
    static bool SameDevice(Device a, Device b) {
        return a != null && b != null && a.AppId == b.AppId &&
            a.Firmware == b.Firmware && a.Model == b.Model;
    }
    static void Guard(Device device) {
        Require(device != null && device.AppId != null &&
            Regex.IsMatch(device.AppId, @"\A[A-Za-z0-9]{10}\.[A-Za-z0-9_]+\z"), "Invalid target ID");
        Require(!String.IsNullOrWhiteSpace(device.Firmware) && !String.IsNullOrWhiteSpace(device.Model),
            "Missing firmware/model guard");
        Require(IntPtr.Size == 4 && getuid() == 901, "Expected 32-bit SDK UID 901, no root");
        var fields = new HashSet<string>(File.ReadAllLines("/etc/prd_info.ini"));
        Require(fields.Contains("Version=" + device.Firmware + ";") &&
            fields.Contains("Model=" + device.Model + ";"), "Firmware/model differs; stop for review");
    }
    static string ReadString(string key) {
        IntPtr value = vconf_get_str(key);
        Require(value != IntPtr.Zero, "Cannot read " + key);
        try { return Marshal.PtrToStringAnsi(value); } finally { free(value); }
    }
    static string Home() {
        IntPtr bundle = bundle_create();
        Require(bundle != IntPtr.Zero, "Cannot create native bundle");
        try {
            Require(aul_svc_set_operation(bundle, Operation) == 0, "Cannot select Home operation");
            IntPtr app;
            Require(aul_get_default_app(bundle, out app) == 0 && app != IntPtr.Zero,
                "Cannot query native Home assignment");
            try { return Marshal.PtrToStringAnsi(app); } finally { free(app); }
        } finally { bundle_free(bundle); }
    }
    static Snapshot Query(Device device, bool checkBoot) {
        var result = new Snapshot { Device = device, Home = Home(),
            Strings = new Dictionary<string, string>(), Uid = getuid(),
            BootSupported = checkBoot ? util_is_appbooting_supported_webapp_byappid(device.AppId) : -1 };
        foreach (var key in Keys) result.Strings[key] = ReadString(key);
        int value;
        Require(vconf_get_int(AutoKey, out value) == 0, "Cannot read autostart");
        result.Autostart = value;
        return result;
    }
    static void ValidateOriginal(Snapshot original, Device device) {
        Require(original != null && SameDevice(original.Device, device), "Original belongs to another target");
        Require(original.Uid == 901 && original.BootSupported == 1, "Original compatibility was not established");
        Require(!String.IsNullOrWhiteSpace(original.Home) && original.Home != device.AppId,
            "Original must name the pre-existing Home app");
        Require(original.Strings != null && original.Strings.Count == Keys.Length &&
            (original.Autostart == 0 || original.Autostart == 1), "Invalid original types");
        foreach (var key in Keys) Require(original.Strings.ContainsKey(key) &&
            !String.IsNullOrWhiteSpace(original.Strings[key]), "Missing original " + key);
    }
    static void EqualSettings(Snapshot actual, Snapshot expected) {
        Require(actual.Home == expected.Home && actual.Autostart == expected.Autostart,
            "Home/autostart differs from expected state");
        foreach (var key in Keys) Require(actual.Strings[key] == expected.Strings[key],
            "Setting differs from expected state: " + key);
    }
    static void SetHome(string app) {
        Require(app_operation_set_current_app(Operation, app) == 0 && Home() == app,
            "Home write/readback failed");
    }
    static void SetString(string key, string value) {
        Require(vconf_set_str(key, value) == 0 && ReadString(key) == value,
            "String write/readback failed: " + key);
    }
    static void SetAuto(int value) {
        int actual;
        Require(vconf_set_int(AutoKey, value) == 0 &&
            vconf_get_int(AutoKey, out actual) == 0 && actual == value,
            "Autostart write/readback failed");
    }
    static void Restore(Device device, Snapshot original) {
        SetHome(original.Home);
        foreach (var key in Keys) SetString(key, original.Strings[key]);
        SetAuto(original.Autostart);
        EqualSettings(Query(device, false), original);
    }
    static void Emit(string kind, Snapshot value) {
        Console.WriteLine("PARAMHOME_" + kind + "=" + JsonSerializer.Serialize(value));
    }
    static int Main(string[] args) {
        try {
            Require(args.Length >= 2 && args.Length <= 3 &&
                (args[0] == "query" || args[0] == "apply" || args[0] == "restore"),
                "Use query CONFIG or apply/restore CONFIG ORIGINAL");
            var device = JsonSerializer.Deserialize<Device>(File.ReadAllText(args[1]));
            Guard(device);
            if (args[0] == "query") {
                Require(args.Length == 2, "Unexpected query arguments");
                Require(Directory.Exists("/opt/usr/apps/" + device.AppId.Split('.')[0]), "Launcher not installed");
                Emit("QUERY", Query(device, true));
                return 0;
            }
            Require(args.Length == 3, "Original snapshot required");
            var original = JsonSerializer.Deserialize<Snapshot>(File.ReadAllText(args[2]));
            ValidateOriginal(original, device);
            var before = Query(device, args[0] == "apply");
            Require(before.Home == original.Home || before.Home == device.AppId,
                "Home was reassigned elsewhere; stop for review");
            if (args[0] == "restore") {
                Restore(device, original);
                Emit("RESTORED", Query(device, false));
                return 0;
            }
            EqualSettings(before, original);
            Require(before.BootSupported == 1 &&
                Directory.Exists("/opt/usr/apps/" + device.AppId.Split('.')[0]),
                "Installed launcher is not eligible for startup");
            try {
                SetHome(device.AppId);
                SetString("db/appfw/home_appid", device.AppId);
                SetAuto(1);
                var after = Query(device, true);
                Require(after.Home == device.AppId && after.Autostart == 1 &&
                    after.Strings["db/appfw/home_appid"] == device.AppId,
                    "Applied state did not read back correctly");
                // Firmware may derive startup/backup from Home; first-screen is preserved.
                Require(after.Strings["db/first_screen/type"] == original.Strings["db/first_screen/type"],
                    "Unexpected first-screen change");
                Emit("APPLIED", after);
            } catch (Exception applyError) {
                Console.Error.WriteLine("Apply failed: " + applyError.Message);
                try { Restore(device, original); Emit("ROLLBACK", Query(device, false)); }
                catch (Exception restoreError) {
                    throw new Exception("AUTOMATIC RESTORE FAILED; inspect current state. " + restoreError.Message, applyError);
                }
                throw new Exception("Original settings restored after failed apply", applyError);
            }
            return 0;
        } catch (Exception error) {
            Console.Error.WriteLine(error.ToString());
            return 1;
        }
    }
}
