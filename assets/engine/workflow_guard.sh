#!/system/bin/sh
# A dead background process must not permanently block future recovery.
# Only removes a stale operation marker; never touches saved networks or profiles.
thor_worker_alive() {
    for process in /proc/[0-9]*/cmdline; do
        [ -r "$process" ] || continue
        arguments=$(tr '\000' ' ' < "$process" 2>/dev/null) || continue
        case "$arguments" in
            *'/data/local/thor-wifi/bin/workflow.sh worker'*|*'/data/local/thor-wifi/bin/workflow.sh connect'*|*'/data/local/thor-wifi/bin/wifi_reconnect.sh'*) return 0;;
        esac
    done
    return 1
}
# A reboot or a killed Binder request can bypass app_api's EXIT trap.
# Protect fresh acquisitions and any other live API process before reclaiming.
thor_clear_app_lock() {
    [ -d "$P/app-lock" ] && [ ! -L "$P/app-lock" ] || return 0
    lock_changed=$(stat -c %Y "$P/app-lock" 2>/dev/null) || return 0
    case "$lock_changed" in ''|*[!0-9]*) return 0;; esac
    [ $(($(date +%s) - lock_changed)) -ge 15 ] || return 0
    for process in /proc/[0-9]*/cmdline; do
        [ "$process" != "/proc/$$/cmdline" ] || continue
        [ -r "$process" ] || continue
        arguments=$(tr '\000' ' ' < "$process" 2>/dev/null) || continue
        case "$arguments" in *'/data/local/thor-wifi/bin/app_api.sh '*) return 0;; esac
    done
    [ "$(stat -c %Y "$P/app-lock" 2>/dev/null)" = "$lock_changed" ] || return 0
    # Only an empty, unchanged lock can be reclaimed; unexpected contents stay.
    rmdir "$P/app-lock" 2>/dev/null || :
}
thor_clear_stale() {
    thor_clear_app_lock
    [ -f "$P/working" ] || return 0
    changed=$(stat -c %Y "$P/working" 2>/dev/null) || return 0
    case "$changed" in ''|*[!0-9]*) return 0;; esac
    # Protect the short interval between writing the marker and spawning a worker.
    [ $(($(date +%s) - changed)) -ge 15 ] || return 0
    thor_worker_alive && return 0
    [ "$(stat -c %Y "$P/working" 2>/dev/null)" = "$changed" ] || return 0
    rm -f "$P/working" "$P/worker.pid"
    printf '%s\n' WORKER_INTERRUPTED > "$P/status"
    printf '%s\n' WORKER_INTERRUPTED > "$P/connection-reason"
}
