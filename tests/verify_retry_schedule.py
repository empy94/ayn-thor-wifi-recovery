"""Mock the post-boot retry schedule without touching Android or rebooting."""

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


BASE = Path(__file__).resolve().parent
if os.name == "nt":
    BASH = Path(r"C:\Program Files\Git\bin\bash.exe")
else:
    BASH = Path(shutil.which("bash") or "/bin/bash")


def shell_path(path: Path) -> str:
    resolved = str(path.resolve()).replace("\\", "/")
    if os.name == "nt":
        return "/" + resolved[0].lower() + resolved[2:]
    return resolved


def write_lf(path: Path, content: str) -> None:
    with path.open("w", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


source = (BASE.parent / "assets/engine/workflow.sh").read_text(encoding="utf-8")

with tempfile.TemporaryDirectory(prefix="retry-test-", dir=BASE) as temp:
    root = Path(temp)
    private = root / "private"
    binary = private / "bin"
    binary.mkdir(parents=True)
    write_lf(binary / "workflow_guard.sh", "thor_clear_stale() { :; }\n")
    write_lf(binary / "wifi_reconnect.sh", "#!/system/bin/sh\nexit 99\n")
    public = root / "WIFI_RESEAUX.txt"
    write_lf(public, "SSID=Thor Test\nMOT_DE_PASSE=DummyOnly123!\n")
    write_lf(private / "credentials", "Thor Test\nDummyOnly123!\n")

    script = source.replace("/data/local/thor-wifi", shell_path(private))
    script = script.replace(
        "/sdcard/Download/Thor-Scripts/WIFI_RESEAUX.txt", shell_path(public)
    )
    workflow = root / "workflow.sh"
    write_lf(workflow, script)

    harness = r'''
id() { echo 0; }
stat() {
    target="${@: -1}"
    if [ "$target" = "$TEST_PRIVATE" ]; then echo 0:0:700; else echo 0:0:600; fi
}
cat() {
    if [ "$1" = /proc/sys/kernel/random/boot_id ]; then echo CURRENT_BOOT;
    else command cat "$@"; fi
}
sleep() { echo "$1" >> "$TEST_DIR/sleeps"; }
reboot() { touch "$TEST_DIR/reboot-called"; return 99; }
timeout() {
    shift 3
    if [ "$1" = /system/bin/sh ] && [ "$2" = "$TEST_PRIVATE/bin/wifi_reconnect.sh" ]; then
        count=0
        [ ! -f "$TEST_DIR/attempts" ] || count=$(wc -l < "$TEST_DIR/attempts")
        count=$((count + 1))
        echo "$count" >> "$TEST_DIR/attempts"
        echo "mock reconnect attempt $count"
        case "$CASE" in
            all_fail) return 3 ;;
            third_success) [ "$count" -ge 3 ]; return ;;
            *) return 0 ;;
        esac
    fi
    "$@"
}

if [ "$CASE" = manual ]; then
    set -- connect
else
    echo PREVIOUS_BOOT > "$TEST_PRIVATE/working"
    set -- worker
fi
. "$TEST_WORKFLOW"
'''
    runner = root / "harness.sh"
    write_lf(runner, harness)

    cases = {
        "first_success": (0, ["5"], 1, "CONNECTED_WITH_IP"),
        "third_success": (0, ["5", "10", "15"], 3, "CONNECTED_WITH_IP"),
        "all_fail": (
            3,
            ["5", "10", "15"],
            3,
            "RECONNECT_NOT_CONFIRMED_AFTER_3_ATTEMPTS_RC=3",
        ),
        "manual": (0, [], 1, "CONNECTED_WITH_IP"),
    }

    for case, (expected_code, expected_sleeps, expected_attempts, expected_status) in cases.items():
        for artifact in (
            "attempts",
            "sleeps",
            "reboot-called",
        ):
            (root / artifact).unlink(missing_ok=True)
        for artifact in (
            "working",
            "worker.pid",
            "status",
            "last-connect-result",
            "operation-worker.txt",
            "operation-connect.txt",
        ):
            (private / artifact).unlink(missing_ok=True)

        env = dict(
            os.environ,
            CASE=case,
            TEST_DIR=shell_path(root),
            TEST_PRIVATE=shell_path(private),
            TEST_WORKFLOW=shell_path(workflow),
        )
        result = subprocess.run(
            [str(BASH), shell_path(runner)],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )

        assert result.returncode == expected_code, (case, result.stdout, result.stderr)
        sleeps_file = root / "sleeps"
        sleeps = sleeps_file.read_text().split() if sleeps_file.exists() else []
        attempts = (root / "attempts").read_text().split()
        assert sleeps == expected_sleeps, (case, sleeps)
        assert len(attempts) == expected_attempts, (case, attempts)
        assert (private / "status").read_text().strip() == expected_status
        assert not (root / "reboot-called").exists(), case
        assert not (private / "working").exists(), case
        assert not (private / "worker.pid").exists(), case

        log = (private / "last-connect-result").read_text()
        expected_delays = expected_sleeps if expected_sleeps else ["0"]
        for attempt, delay in enumerate(expected_delays, start=1):
            assert f"ATTEMPT {attempt} / DELAY {delay}s" in log, (case, log)
        assert "DummyOnly123!" not in result.stdout + result.stderr + log
        print(f"PASS {case}: sleeps={expected_sleeps}, attempts={expected_attempts}")

print("Mock validation only; no Android command or reboot was executed.")
