#!/bin/bash
# WiFi setup script for the Sky Q Controller Pi
# Copy this file to wifi-setup.sh, fill in real values, then run it.
# Do NOT commit wifi-setup.sh (with real passwords) to Git - only this template.

sudo nmcli connection add type wifi con-name "Home" ssid "YOUR_HOME_SSID" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "YOUR_HOME_PASSWORD"

sudo nmcli connection add type wifi con-name "Remote" ssid "REMOTE_SSID" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "REMOTE_PASSWORD"

sudo nmcli connection add type wifi con-name "Hotspot" ssid "YOUR_HOTSPOT_SSID" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "YOUR_HOTSPOT_PASSWORD"

echo "WiFi networks added. Check with: sudo nmcli connection show"
