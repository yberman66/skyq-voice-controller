# Sky Q Voice Controller

Flask app running on a Raspberry Pi Zero 2W. Receives voice commands from
Siri Shortcuts (via HTTP POST) and controls Sky Q boxes (using pyskyqremote)
and Samsung TVs (over the network), in two rooms.

Printable one-page cards for the person using it are in `reference-card.md`
and `Sky_Q_voice_commands.docx`.

## Hardware
- Raspberry Pi Zero 2W (hostname: skypi)
- Lives at the user's home, connected to their WiFi
- Remotely accessible via Tailscale

## Rooms

One copy of app.py runs per room. Each copy is configured with environment
variables (all optional - the defaults in app.py are the bedroom).

| Room    | Service              | Port | Sky box          | TV                          |
|---------|----------------------|------|------------------|-----------------------------|
| Bedroom | skyq-controller      | 8080 | 192.168.0.XX     | Samsung, 192.168.0.YY       |
| Kitchen | skyq-kitchen         | 8081 | 192.168.0.AA     | Samsung, 192.168.0.BB       |

Environment variables read by app.py: PORT, SKYQ_BOX_IP, TV_IP, TV_MAC,
TV_TOKEN_FILE, SAVED_VOLUME_FILE, SKY_PAUSED_FILE, FORWARD_PHONE_URL (the
last is only set on the bedroom service - see "Phone and WhatsApp calls").

Each TV's MAC address is needed (TV_MAC) for Wake-on-LAN. A TV on wifi has a
different MAC from its wired one - use the one for the connection it actually
uses (Settings > General > Network > Network Status). The Sky boxes' MACs are
only needed for router address reservations.

The kitchen service file is in this repo as skyq-kitchen.service.

### Router (Sky Hub, http://192.168.0.1) address reservations
Advanced > LAN IP Setup > Address Reservation. Reserve the Pi, both Sky boxes
and both TVs so their addresses never change. The hub refuses two reservations
with the same device name ("Device name already exists"), so give the second
room's devices different names (for example KitchenTV and KitchenSky). Press
Apply on the main page after adding, or nothing is saved.

## If the SD card ever fails - full rebuild steps

1. Flash a fresh SD card with Raspberry Pi OS Lite (arm64), using Raspberry
   Pi Imager. Set hostname `skypi`, enable SSH, set username `pi`.

2. Boot the Pi, SSH in:

   ```
   ssh pi@skypi.local
   ```

3. Update the OS:

   ```
   sudo apt update && sudo apt full-upgrade -y
   sudo reboot
   ```

4. Install essentials:

   ```
   sudo apt install python3-pip python3-venv git nmap -y
   ```

5. Clone this repo:

   ```
   git clone https://github.com/yberman66/skyq-voice-controller.git ~/skyq-controller
   cd ~/skyq-controller
   ```

6. Set up the WiFi networks:
   - Copy `wifi-setup-template.sh` to `wifi-setup.sh`
   - Fill in the real SSIDs and passwords (get these from wherever you store
     them - e.g. a password manager)
   - Run it: `bash wifi-setup.sh`

7. Create the virtual environment and install dependencies:

   ```
   python3 -m venv venv
   source venv/bin/activate
   pip install flask pyskyqremote samsungtvws
   ```

   The service uses the venv python, so samsungtvws must be installed INTO
   the venv or the service crash-loops with ModuleNotFoundError.

8. Check the addresses in app.py / the service files match the table above.

9. Install the systemd services:

   ```
   sudo cp skyq-controller.service /etc/systemd/system/
   sudo cp skyq-kitchen.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable --now skyq-controller.service
   sudo systemctl enable --now skyq-kitchen.service
   sudo systemctl status skyq-controller.service skyq-kitchen.service
   ```

   Then add the call-forwarding drop-in to the BEDROOM service only (it is
   not stored in this repo; see "Phone and WhatsApp calls"):

   ```
   sudo mkdir -p /etc/systemd/system/skyq-controller.service.d
   printf '[Service]\nEnvironment=FORWARD_PHONE_URL=http://127.0.0.1:8081/command\n' | sudo tee /etc/systemd/system/skyq-controller.service.d/forward.conf
   sudo systemctl daemon-reload
   sudo systemctl restart skyq-controller
   ```

10. Pair each TV (the tokens are NOT in git - see "TV control" below).

11. Install Tailscale:

    ```
    curl -fsSL https://tailscale.com/install.sh | sh
    sudo tailscale up
    ```

    Approve the new device in the Tailscale admin console, and disable key
    expiry for this device.

12. Test:

    ```
    curl http://skypi.local:8080/health
    curl http://skypi.local:8081/health
    ```

    Each should return `{"status":"ok"}`.

13. Re-test the Siri Shortcuts on the phone (already built - just confirm
    they still point at the right URLs and ports).

14. Install the WiFi power-save fix and connectivity watchdog (see below).

State files live outside the repo in /home/pi (tv-token.txt,
tv-token-kitchen.txt, saved-volume*.json, sky-paused*.flag). Only the tokens
matter for a rebuild.

## Siri Shortcuts (on the user's iPhone)
- Bedroom shortcut: Get Contents of URL, POST, JSON with `phrase` set to the
  spoken text, to `http://skypi.local:8080/command`
- Kitchen shortcut: a duplicate of the bedroom one, renamed, with the URL
  changed to `http://skypi.local:8081/command` (only the port differs).
  The user says "Hey Siri" followed by the kitchen shortcut's name, then the
  command.

## Requirements

Works with Sky Q boxes only. Sky Stream does not expose the local interface
that pyskyqremote uses, and Sky Glass almost certainly doesn't either. The TV
control needs a Samsung Tizen smart TV (2016 and later models generally work).

## Siri Shortcut

Build a Shortcut on an iPhone or iPad with two actions:

1. Dictate Text
2. Get Contents of URL:
   - URL: `http://skypi.local:8080/command`
   - Method: POST
   - Request Body: JSON, with a field `phrase` set to the Dictated Text

The Shortcut's name is what you say after "Hey Siri". The first run asks for
local network permission - tap Allow. `skypi.local` only works on the same WiFi
as the Pi; use the Tailscale name for remote use. For a second room, duplicate
the Shortcut, rename it, and change the port to 8081.

## Security

The Flask servers have no authentication and listen on all interfaces, so
anyone on the same network can send them commands. That is fine on a home
network. Do not expose ports 8080 or 8081 to the internet - use Tailscale or
similar for remote access. They also use Flask's built-in development server,
which is adequate for this use.

## Credits

Sky Q control is done by pyskyqremote by Roger Selwyn:
https://github.com/RogerSelwyn/skyq_remote

TV control uses samsungtvws:
https://github.com/xchwarze/samsung-tv-ws-api

## Command map
See COMMAND_MAP in app.py for the full list of recognised phrases.

### Macros
A COMMAND_MAP entry can be a single button or a list of buttons, which
command() sends as a sequence (about half a second apart, so a long macro
takes several seconds).
- "apps" = home, then 10 x down (lands on the Apps heading)
- "netflix" = home, then 10 x down, then 6 x right. It deliberately does NOT
  press select. The Home screen layout is dynamic and the counts were
  hit-and-miss during testing, so it stops near Netflix and the user says
  "left" or "right" to adjust, then "select".
- These counts are blind: they depend on Sky's Home screen layout. If Sky
  changes it, press home on the real remote, count the presses again, and
  update the numbers in app.py.

### Repeat counts
A direction followed by a number repeats that button, e.g. "left 3" or
"down five". Digits and number words (one to ten) both work. This is handled
by repeat_key() in app.py, which only runs when a phrase isn't an exact match
in COMMAND_MAP. It applies to left, right, up and down (and "write", the
common dictation mishearing of "right"). The count is capped at 10
(MAX_REPEAT) so a misheard number can't send a long run of presses.
Presses go out about half a second apart. Because dictation often turns "two"
and "four" into "to" and "for", those spellings are accepted too. Anything
else, such as "channel 101", is still logged as unrecognised.

### Dictation mishearings
Siri dictation sometimes mishears phrases. The Pi returns a 400 and logs
"Unrecognised phrase" for anything not recognised. Added so far:
"write" and "write it" (= right), "change up" and "change down" (= channel
up/down), and "scroll up" and "scroll down" (= up/down). To find new ones:

```
sudo journalctl -u skyq-controller --no-pager | grep Unrecognised
```

Dictation also picks up background conversation, which shows up as long
unrecognised phrases in the log. Not yet added: "paul" (heard for "pause").

### Known behaviour
- In apps such as Netflix, "select" needs something highlighted first. Say
  "left" or "right" first.
- Sky Q: the "pause" key does nothing inside Netflix; the "play" key toggles
  play/pause there. On live TV and recordings "pause" works. The phone-call
  logic checks get_active_application() to pick the right key.
- The Sky "power" key is a toggle, so "power on"/"power off" read
  power_status() first and only press if the state differs. After waking, the
  box can take about 45 seconds to report ON, so a quick on-then-off can say
  "already off".

## TV control (Samsung, both rooms)

Commands handled before the Sky box logic in command():
- "volume up/down [n]", "louder", "quieter" - KEY_VOLUP/KEY_VOLDOWN, repeated
  up to MAX_TV_REPEAT (15). "volume up 3" or "volume up three".
- "mute" / "unmute" - KEY_MUTE. The TV's mute is a TOGGLE, both send the same
  key.
- "volume 20", "set volume 20", "volume to twenty" - sets the exact level via
  UPnP RenderingControl on port 9197 (GetVolume/SetVolume). Capped at
  MAX_SET_VOLUME (60) in app.py - raise it if the user wants it louder. Number
  words only go one to ten; larger numbers must be digits.
- "power on" / "turn on" / "switch on" / "on" - wakes the TV with a
  Wake-on-LAN packet (TV_MAC) and turns the Sky box on if it is off.
- "power off" / "turn off" / "switch off" / "shut down" / "off" - TV to
  standby (KEY_POWER) and Sky box off, each only if currently on.

How it connects: samsungtvws over the websocket on port 8002, with a token
file (tv-token.txt bedroom, tv-token-kitchen.txt kitchen). A new connection is
made per request so it works after the TV has been off.

Things learned (so they are not rediscovered):
- KEY_POWEROFF is ignored by these TVs; KEY_POWER toggles to standby.
- In deep standby the TV drops off the network and the websocket times out.
  Only Wake-on-LAN brings it back ("Power On with Mobile" must be enabled in
  the TV's network settings). tv_is_on() is a TCP connect to port 8002.
- The TV's REST API on :8001 has no usable PowerState.
- KEY_PAUSE/PLAY/ENTER do not pause Netflix on the TV itself - pausing is
  done through the Sky box instead.

### Pairing a TV (once per TV, not stored in git)
Keep the TV on and run, from the Pi (use the TV's address and its own token
file name, for example 192.168.0.BB and /home/pi/tv-token-kitchen.txt):

```
/home/pi/skyq-controller/venv/bin/python - <<'EOF'
from samsungtvws import SamsungTVWS
tv = SamsungTVWS(host="192.168.0.BB", port=8002, token_file="/home/pi/tv-token-kitchen.txt", name="SkyPi", timeout=30)
tv.send_key("KEY_VOLUP")
print("sent")
EOF
```

Approve "Allow SkyPi?" on the TV screen within about 30 seconds. The token
file is created on success.

## Phone and WhatsApp calls (both rooms)

When a call rings, an iPhone Shortcuts automation POSTs `{"phrase": "phone"}`
to `http://skypi.local:8080/command`. The Pi then:
1. Saves the current TV volume (to saved-volume.json) and sets it to 0.
2. Pauses the Sky box (the first ring only): sends "play" if an app such as
   Netflix is active, otherwise "pause". Writes sky-paused.flag.
Repeat rings during the same call only re-silence; they do not pause again.

The user restores everything by saying "play" (also "volume back", "restore
volume", "call finished", "back to normal"): the volume goes back, and for
"play" the Sky box resumes. If nothing was saved, "play" just acts as a normal
Sky play key.

Saved state is ignored after an hour (SAVED_VOLUME_MAX_AGE). If the user forgets
to say "play" and another call comes in within the hour, the TV is muted again
but the Sky box is NOT paused - the Pi thinks the first call is still going.

iPhone automations (Shortcuts > Automation):
- Phone: trigger "When I receive a notification from Phone", Run Immediately,
  Notify off. Action: Get Contents of URL (POST, JSON, phrase = phone).
  Only a ringing call produces this notification, so it needs no filter.
- WhatsApp: same, from WhatsApp, but with the filter Message contains
  "Incoming" (WhatsApp call notifications read "Incoming voice/video call").
  Without the filter, every WhatsApp message fires it. In the iOS filter list
  the notification body is called "Message".
- URL typo to avoid: it must be `http://skypi.local:8080/command` (or the Pi's
  address and port), not a mistyped address such as `192.168.073`.
- Kitchen: the automations only call the bedroom service (port 8080). The
  bedroom service passes every "phone" request on to the kitchen service
  (port 8081) itself, so nothing needs changing on the user's phone. If the
  user cannot operate their phone by hand, this is much easier than editing the
  automations.

### How the kitchen gets told about a call
app.py has forward_phone(): if the environment variable FORWARD_PHONE_URL is
set, a "phone" request is also POSTed to that URL in a background thread (20
second timeout; failure is only logged, as "Could not forward phone call").
It is set only on the bedroom service, by a systemd drop-in:

```
/etc/systemd/system/skyq-controller.service.d/forward.conf
[Service]
Environment=FORWARD_PHONE_URL=http://127.0.0.1:8081/command
```

The kitchen service has no such setting, so the two can never forward to each
other in a loop. The kitchen copy only acts if its TV and Sky box are actually
on: a TV that is off is skipped (logged as "failed") and a Sky box in standby
is left alone. The user restores a room by saying "play" to that room's
shortcut.

Check that it worked after a real call:

```
sudo journalctl -u skyq-controller --since "10 minutes ago" --no-pager | grep -E "Phone call|Forwarded"
sudo journalctl -u skyq-kitchen --since "10 minutes ago" --no-pager | grep "Phone call"
```

To switch the forwarding off (for example if the second action is ever added
to the phone automations instead):

```
sudo rm /etc/systemd/system/skyq-controller.service.d/forward.conf
sudo systemctl daemon-reload
sudo systemctl restart skyq-controller
```

### Resetting stuck call state
If the TV mutes but the Sky box doesn't pause (the log says "already handled
this call"), clear the saved state and reset the volume (run these as two
separate commands):

```
rm -f /home/pi/saved-volume.json /home/pi/sky-paused.flag
curl -s -X POST localhost:8080/command -H 'Content-Type: application/json' -d '{"phrase":"volume 20"}'
```

For the kitchen use saved-volume-kitchen.json, sky-paused-kitchen.flag and
port 8081.

## Reliability fixes

**WiFi power save.** The Pi Zero 2W's WiFi chip can go into power-saving
mode and fail to wake, dropping the connection until rebooted. This
happened after about 12 hours of being left idle overnight. Fixed by:

```
sudo cp wifi-powersave-off.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable wifi-powersave-off.service
sudo systemctl start wifi-powersave-off.service
```

This runs `iw wlan0 set power_save off` on every boot.

**Connectivity watchdog.** wifi-watchdog.sh pings 8.8.8.8 every 5 minutes
(via cron). After 3 consecutive failures it reboots the Pi, with a 30
minute minimum gap between reboots to avoid a reboot loop. Logs to
/var/log/wifi-watchdog.log. Installed with:

```
sudo cp wifi-watchdog.sh /usr/local/bin/
sudo chmod +x /usr/local/bin/wifi-watchdog.sh
sudo crontab -e
```

then add:

```
*/5 * * * * /usr/local/bin/wifi-watchdog.sh
```

**Persistent logs.** By default this Pi's logs don't survive a reboot,
which meant a real outage (Sept 2026) left no evidence of its cause.
Raspberry Pi OS ships /usr/lib/systemd/journald.conf.d/40-rpi-volatile-storage.conf,
which forces Storage=volatile and overrides /etc/systemd/journald.conf, so
creating /var/log/journal or editing journald.conf alone does NOT work
(this was tried first and silently failed). Fixed with a later-sorting
drop-in:
```
sudo mkdir -p /etc/systemd/journald.conf.d
printf '[Journal]\nStorage=persistent\nSystemMaxUse=100M\n' | sudo tee /etc/systemd/journald.conf.d/99-persistent.conf
sudo systemctl restart systemd-journald
sudo journalctl --flush
```
Check with `ls /var/log/journal` (should contain a long-named folder) and,
after a reboot, `journalctl --list-boots` (should list more than one boot).
Capped at 100M, so this doesn't grow unbounded.

## Housekeeping

- **Weekly reboot**: cron job set via `sudo crontab -e`, reboots every Sunday
  at 4am (`0 4 * * 0 /sbin/shutdown -r now`). Not stored in this repo - if
  rebuilding, re-add manually.
- **Log size cap**: SystemMaxUse=100M is set in
  /etc/systemd/journald.conf.d/99-persistent.conf (see Persistent logs
  above), to stop logs slowly filling the SD card. Not stored in this repo -
  if rebuilding, re-add manually.
- **Untracked backups**: patch scripts leave app.py.before-* and app.py.bak
  files in the project folder. They are deliberately not committed - use
  `git add app.py`, never `git add .` (with a dot).

## Design Decisions

**Why Siri Shortcuts + Flask, not a dedicated app or physical button?**
The end user needs to control the TV by voice alone. They already use Siri
daily, so the solution needed to slot into something they're already fluent
in, rather than teaching a new interface or requiring physical reach to a
button/remote.

**Why a Raspberry Pi Zero 2W?**
Small, cheap, low power, and fully headless - it needs no screen, sits out
of sight behind the TV, and just runs quietly in the background.

**Why network control (pyskyqremote) rather than an IR blaster?**
Network control doesn't need line of sight, isn't affected by furniture or
the Pi's exact position, and can be tested/managed remotely via SSH. IR was
considered as a fallback if the network approach proved unreliable -
downsides would include needing line of sight to the box, fragility to the
Pi being moved or blocked, and no way to confirm a command was received.

**How does volume control work, given Sky Q has no volume command?**
pyskyqremote's valid command list does not include volume/mute - a genuine
protocol limitation (confirmed in the library source). Instead the Pi talks
to the Samsung TVs directly over the network (see "TV control"): key presses
over the websocket for up/down/mute, and UPnP for setting an exact level.
This does not rely on HDMI-CEC.

**Why does "power on/off" do the TV and the Sky box separately?**
Both the TV and the Sky box power keys are toggles, so each is checked first
(TCP connect to the TV's port 8002; power_status() on the box) and only
changed if needed. One failing does not stop the other.

**Why one app, two copies, instead of one app that knows about rooms?**
Each room is the same code with different environment variables. The
bedroom, which works well, is untouched by anything done for the kitchen, and
each room keeps its own saved volume and pause state so calls and restores
cannot confuse each other. The kitchen Siri shortcut is just the bedroom one
with a different port.

**Why Tailscale rather than Raspberry Pi Connect?**
Consistency with other Pis already using Tailscale,
and it avoids introducing a second remote-access system to maintain.

**Why is there no full SD card disk image backup?**
Unlike Pis running Home Assistant (which have a live database and complex
state), this project has almost no state of its own - just a handful of
small files and a WiFi config. A full image backup was judged unnecessary
overhead; instead, the code is version-controlled in this Git repo, with a
template script for WiFi setup (real passwords deliberately kept out of
Git and stored separately).

## Troubleshooting

Siri Shortcut doesn't seem to do anything:
- Check the Pi is powered on and connected to WiFi.
- From a device on the same WiFi, try `curl http://skypi.local:8080/health`
  (8081 for the kitchen)
- Should return `{"status":"ok"}`. If not, the Flask service isn't running or isn't reachable - see below.

Flask service isn't responding:
- SSH in (`ssh pi@skypi` or `ssh pi@skypi.local`), then check status:
  `sudo systemctl status skyq-controller.service` (kitchen: `skyq-kitchen.service`)
- If not "active (running)", restart it:
  `sudo systemctl restart skyq-controller.service`
- Check logs for errors:
  `sudo journalctl -u skyq-controller -n 30 --no-pager` (kitchen: `-u skyq-kitchen`)
- If the log says ModuleNotFoundError: samsungtvws, the package is missing
  from the venv: `/home/pi/skyq-controller/venv/bin/pip install samsungtvws`

Command sends but nothing happens on the TV or box:
- Confirm the addresses still match the table above. The router reservations
  should stop them moving, but if a device has changed address, find it with:
  `sudo nmap -sn 192.168.0.0/24 | grep -i -B2 -E "samsung|sky"`
- Check a TV answers: `nmap -p 8001,8002,9197 192.168.0.BB` (use the TV's own
  address; all three ports open when it is on).
  A TV in deep standby shows "host seems down" - that is normal.
- If the Sky box IP changed, update SKYQ_BOX_IP (app.py for the bedroom, the
  service file for the kitchen), then restart that service.

TV volume works but nothing else (or vice versa):
- The TV commands and the Sky commands are independent. The TV needs its token
  file; if the TV has been factory reset or "Allow SkyPi?" was denied, delete
  the token file and pair again (see "TV control").

Can't SSH in locally (skypi.local not found):
- Try Tailscale instead: `ssh pi@skypi` (works from anywhere, not just local network)
- If that also fails, check Tailscale status on the Pi in person, or plug in a monitor/keyboard directly.

Pi seems unresponsive after a power cut:
- SD cards can occasionally corrupt on sudden power loss. Try a normal reboot/power cycle first.
- If it doesn't come back at all, see the rebuild steps above - the whole project can be restored from this Git repo in well under an hour (plus re-pairing each TV).

Need to add or change a phrase the user says:
- Edit COMMAND_MAP in app.py, then restart BOTH services:
  `sudo systemctl restart skyq-controller.service skyq-kitchen.service`
- Remember to also `git add app.py`, commit, and push the change, and update the printed one-page reference card if the wording changes.
