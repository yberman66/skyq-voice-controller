# Sky Q Voice Controller

Flask app running on a Raspberry Pi Zero 2W. Receives voice commands from a
Siri Shortcut (via HTTP POST) and sends them to a Sky Q box over the local
network using pyskyqremote.

## Hardware
- Raspberry Pi Zero 2W (hostname: skypi)
- Lives at the user's home, connected to their WiFi
- Remotely accessible via Tailscale

## If the SD card ever fails - full rebuild steps

1. Flash a fresh SD card with Raspberry Pi OS Lite (arm64), using Raspberry
   Pi Imager. Set hostname `skypi`, enable SSH, set username `pi`.

2. Boot the Pi, SSH in:
   ssh pi@skypi.local

3. Update the OS:
   sudo apt update && sudo apt full-upgrade -y
   sudo reboot

4. Install essentials:
   sudo apt install python3-pip python3-venv git -y

5. Clone this repo:
   git clone https://github.com/yberman66/skyq-voice-controller.git ~/skyq-controller
   cd ~/skyq-controller

6. Set up the WiFi networks:
   - Copy wifi-setup-template.sh to wifi-setup.sh
   - Fill in the real SSIDs and passwords (get these from wherever you store
     them - e.g. a password manager)
   - Run it: bash wifi-setup.sh

7. Create the virtual environment and install dependencies:
   python3 -m venv venv
   source venv/bin/activate
   pip install flask pyskyqremote

8. Update SKYQ_BOX_IP in app.py to the actual Sky Q box IP address
   (check on the box: Settings > Setup > Network).

9. Install the systemd service:
   sudo cp skyq-controller.service /etc/systemd/system/
   sudo systemctl daemon-reload
   sudo systemctl enable skyq-controller.service
   sudo systemctl start skyq-controller.service
   sudo systemctl status skyq-controller.service

10. Install Tailscale:
    curl -fsSL https://tailscale.com/install.sh | sh
    sudo tailscale up
    Approve the new device in the Tailscale admin console, and disable key
    expiry for this device.

11. Test:
    curl http://skypi.local:8080/health
    Should return {"status":"ok"}.

12. Test the Siri Shortcut (see the Siri Shortcut section below).

## Requirements
Works with Sky Q boxes only. Sky Stream does not expose the local interface
that pyskyqremote uses, and Sky Glass almost certainly doesn't either.

## Siri Shortcut
Build a Shortcut on an iPhone or iPad with two actions:
1. Dictate Text
2. Get Contents of URL:
   - URL: http://skypi.local:8080/command
   - Method: POST
   - Request Body: JSON, with a field "phrase" set to the Dictated Text

The Shortcut's name is what you say after "Hey Siri". The first run asks for
local network permission - tap Allow. skypi.local only works on the same WiFi
as the Pi; use the Tailscale name for remote use.

## Security
The Flask server has no authentication and listens on all interfaces, so
anyone on the same network can send it commands. That is fine on a home
network. Do not expose port 8080 to the internet - use Tailscale or similar for
remote access. It also uses Flask's built-in development server, which is
adequate for this use.

## Credits
Sky Q control is done by pyskyqremote by Roger Selwyn:
https://github.com/RogerSelwyn/skyq_remote

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

### Dictation mishearings
Siri dictation sometimes mishears phrases. The Pi returns a 400 and logs
"Unrecognised phrase" for anything not in COMMAND_MAP. Added so far:
"write" and "write it" (= right), "change up" and "change down" (= channel
up/down). To find new ones:
  sudo journalctl -u skyq-controller --no-pager | grep Unrecognised
Dictation also picks up background conversation, which shows up as long
unrecognised phrases in the log.

### Known behaviour
- In apps such as Netflix, "select" needs something highlighted first. Say
  "left" or "right" first.
- Netflix ignored "pause" and "stop" in testing, though the Pi sent them
  successfully (logged with a 200). "back" worked.
- The Sky Q box's IP must match SKYQ_BOX_IP in app.py. If it
  changes, see Troubleshooting.

## Housekeeping

- **Weekly reboot**: cron job set via `sudo crontab -e`, reboots every Sunday
  at 4am (`0 4 * * 0 /sbin/shutdown -r now`). Not stored in this repo - if
  rebuilding, re-add manually.
- **Log size cap**: `/etc/systemd/journald.conf` has `SystemMaxUse=100M` set,
  to stop logs slowly filling the SD card. Not stored in this repo - if
  rebuilding, re-add manually (uncomment and set that line, then
  `sudo systemctl restart systemd-journald`).

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

**Why isn't volume control supported?**
pyskyqremote's valid command list does not include volume/mute - this is a
genuine protocol limitation, not an oversight. Sky Q normally passes volume
control to the TV via HDMI-CEC, which is a separate mechanism this project
doesn't currently touch. Confirmed by checking the pyskyqremote library's
source directly.

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

**Does the "power" command turn the TV on/off too?**
Only indirectly, via HDMI-CEC (the TV's own feature for accepting signals
from connected HDMI devices). This depends on the TV having CEC enabled -
worth checking directly rather than assuming.

## Troubleshooting

Siri Shortcut doesn't seem to do anything:
- Check the Pi is powered on and connected to WiFi.
- From a device on the same WiFi, try: curl http://skypi.local:8080/health
- Should return {"status":"ok"}. If not, the Flask service isn't running or isn't reachable - see below.

Flask service isn't responding:
- SSH in (ssh pi@skypi or ssh pi@skypi.local), then check status:
  sudo systemctl status skyq-controller.service
- If not "active (running)", restart it:
  sudo systemctl restart skyq-controller.service
  sudo systemctl status skyq-controller.service
- Check logs for errors:
  sudo journalctl -u skyq-controller -n 30 --no-pager

Command sends but nothing happens on the TV:
- Confirm SKYQ_BOX_IP in app.py is still correct - if the router reassigned the box a new IP (no static IP set), this will silently stop working. Check the box's IP directly: Settings > Setup > Network on the Sky Q box.
- If the IP changed, update SKYQ_BOX_IP in app.py, then:
  sudo systemctl restart skyq-controller.service

Can't SSH in locally (skypi.local not found):
- Try Tailscale instead: ssh pi@skypi (works from anywhere, not just local network)
- If that also fails, check Tailscale status on the Pi in person, or plug in a monitor/keyboard directly.

Pi seems unresponsive after a power cut:
- SD cards can occasionally corrupt on sudden power loss. Try a normal reboot/power cycle first.
- If it doesn't come back at all, see the rebuild steps above - the whole project can be restored from this Git repo in well under an hour.

Need to add or change a phrase the user says:
- Edit COMMAND_MAP in app.py, then:
  sudo systemctl restart skyq-controller.service
- Remember to also git add, commit, and push the change, and update the printed one-page reference card if the wording changes.
