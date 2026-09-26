#!/bin/bash
# Checks internet connectivity; reboots after 3 consecutive failures.
# Won't reboot more than once every 30 minutes, to avoid a reboot loop.

LOGFILE="/var/log/wifi-watchdog.log"
FAILCOUNT_FILE="/tmp/wifi-watchdog-failcount"
LAST_REBOOT_FILE="/tmp/wifi-watchdog-last-reboot"

FAILCOUNT=$(cat "$FAILCOUNT_FILE" 2>/dev/null || echo 0)

if ping -c 1 -W 5 8.8.8.8 >/dev/null 2>&1; then
    if [ "$FAILCOUNT" -gt 0 ]; then
        echo "$(date): connection OK, resetting fail count" >> "$LOGFILE"
    fi
    echo 0 > "$FAILCOUNT_FILE"
else
    FAILCOUNT=$((FAILCOUNT + 1))
    echo "$(date): ping failed, fail count = $FAILCOUNT" >> "$LOGFILE"
    echo "$FAILCOUNT" > "$FAILCOUNT_FILE"

    if [ "$FAILCOUNT" -ge 3 ]; then
        LAST_REBOOT=$(cat "$LAST_REBOOT_FILE" 2>/dev/null || echo 0)
        NOW=$(date +%s)
        SECONDS_SINCE_REBOOT=$((NOW - LAST_REBOOT))

        if [ "$SECONDS_SINCE_REBOOT" -gt 1800 ]; then
            echo "$(date): 3 consecutive failures, rebooting" >> "$LOGFILE"
            echo "$NOW" > "$LAST_REBOOT_FILE"
            echo 0 > "$FAILCOUNT_FILE"
            /sbin/reboot
        else
            echo "$(date): would reboot, but rebooted too recently" >> "$LOGFILE"
        fi
    fi
fi
