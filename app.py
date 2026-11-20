"""
Sharon's Sky Q Voice Controller
Runs on Pi Zero 2W. Receives commands from Siri Shortcuts (via HTTP POST)
and sends them to a Sky Q box over the local network using pyskyqremote.
"""

import logging
import json
import os
import re
import socket
import threading
import time
import urllib.request
from flask import Flask, request, jsonify
from pyskyqremote.skyq_remote import SkyQRemote
from samsungtvws import SamsungTVWS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("skyq-controller")

app = Flask(__name__)

# ---------------------------------------------------------------------------
# CONFIG - fill this in once you know the Sky Q box's IP address on the
# target network (your friend's, then later Sharon's). pyskyqremote can
# often auto-discover, but a fixed IP is more reliable for a hidden device.
# ---------------------------------------------------------------------------
SKYQ_BOX_IP = os.environ.get("SKYQ_BOX_IP", "192.168.0.XX")  # <-- update this once you're on-site

sky = None  # created lazily so the app still starts even if the box isn't reachable yet


def get_sky():
    """Connect to the Sky Q box on first use, reuse the connection after that."""
    global sky
    if sky is None:
        log.info("Connecting to Sky Q box at %s", SKYQ_BOX_IP)
        sky = SkyQRemote(SKYQ_BOX_IP)
    return sky


# ---------------------------------------------------------------------------
# COMMAND MAP - spoken phrase -> pyskyqremote button code
# Extend this list freely; keys should be lowercase, what Siri will send.
# ---------------------------------------------------------------------------
COMMAND_MAP = {
    "power": "power",
    "on": "power",
    "off": "power",
    "power off": "power",
    "turn off": "power",
    "shut down": "power",
    "scroll down": "down",
    "scroll up": "up",
    "pause": "pause",
    "play": "play",
    "stop": "stop",
    "rewind": "rewind",
    "fast forward": "fastforward",
    "up": "up",
    "down": "down",
    "left": "left",
    "right": "right",
    "write": "right",
    "write it": "right",
    "select": "select",
    "back": "backup",
    "home": "home",
    "channel up": "channelup",
    "change up": "channelup",
    "channel down": "channeldown",
    "change down": "channeldown",
    "record": "record",
    "tv guide": "tvguide",
    "sky": "home",
    "search": "search",
    "0": "0", "1": "1", "2": "2", "3": "3", "4": "4",
    "5": "5", "6": "6", "7": "7", "8": "8", "9": "9",
    "apps": ["home"] + ["down"] * 10,
    "netflix": ["home"] + ["down"] * 10 + ["right"] * 6,
    "phone": "pause",
}

NUMBER_WORDS = {
    "one": 1, "two": 2, "to": 2, "too": 2, "three": 3, "four": 4, "for": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}
REPEATABLE = {"left", "right", "up", "down", "write"}
MAX_REPEAT = 10

# ---------------------------------------------------------------------------
# TV CONTROL (Samsung UE65NU7400, bedroom) - volume and mute over the network.
# The TV's IP is reserved in the router. The token file is created when the
# TV's "Allow SkyPi?" pop-up is approved.
# ---------------------------------------------------------------------------
TV_IP = os.environ.get("TV_IP", "192.168.0.YY")
TV_TOKEN_FILE = os.environ.get("TV_TOKEN_FILE", "/home/pi/tv-token.txt")
MAX_TV_REPEAT = 15

TV_COMMANDS = {
    "volume up": "KEY_VOLUP",
    "volume down": "KEY_VOLDOWN",
    "louder": "KEY_VOLUP",
    "quieter": "KEY_VOLDOWN",
    "mute": "KEY_MUTE",
    "unmute": "KEY_MUTE",  # the TV's mute is a toggle, so both send the same key
}


def tv_command(phrase):
    # 'volume up 3' -> ['KEY_VOLUP'] * 3, 'mute' -> ['KEY_MUTE'], else None
    parts = phrase.split()
    count = 1
    if len(parts) > 1:
        n = int(parts[-1]) if parts[-1].isdigit() else NUMBER_WORDS.get(parts[-1])
        if n is not None:
            count = n
            parts = parts[:-1]
    key = TV_COMMANDS.get(" ".join(parts))
    if key is None:
        return None
    if key == "KEY_MUTE":
        count = 1
    if not 1 <= count <= MAX_TV_REPEAT:
        return None
    return [key] * count


def send_tv_keys(keys, linger=0.0):
    # new connection per request, so it still works after the TV has been off
    tv = SamsungTVWS(host=TV_IP, port=8002, token_file=TV_TOKEN_FILE, name="SkyPi", timeout=5)
    try:
        for k in keys:
            tv.send_key(k)
            time.sleep(0.2)
    finally:
        time.sleep(linger)
        tv.close()


MAX_SET_VOLUME = 60  # safety cap for "volume N" - raise it if Sharon wants it louder


def parse_set_volume(phrase):
    # 'volume 15', 'set volume 15', 'volume to fifteen' -> 15, else None
    m = re.fullmatch(r"(?:set )?volume (?:to |at )?(\w+)", phrase)
    if not m:
        return None
    w = m.group(1)
    return int(w) if w.isdigit() else NUMBER_WORDS.get(w)


def set_tv_volume(level):
    body = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        '<s:Body><u:SetVolume xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">'
        '<InstanceID>0</InstanceID><Channel>Master</Channel>'
        '<DesiredVolume>%d</DesiredVolume></u:SetVolume></s:Body></s:Envelope>' % level
    )
    req = urllib.request.Request(
        "http://%s:9197/upnp/control/RenderingControl1" % TV_IP,
        data=body.encode(),
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": '"urn:schemas-upnp-org:service:RenderingControl:1#SetVolume"',
        },
    )
    urllib.request.urlopen(req, timeout=5).read()


def repeat_key(phrase):
    """'left 3' or 'down five' -> list of repeated presses, else None."""
    parts = phrase.split()
    if len(parts) != 2 or parts[0] not in REPEATABLE:
        return None
    base = COMMAND_MAP.get(parts[0])
    if not isinstance(base, str):
        return None
    count = int(parts[1]) if parts[1].isdigit() else NUMBER_WORDS.get(parts[1])
    if count is None or not 1 <= count <= MAX_REPEAT:
        return None
    return [base] * count


TV_MAC = os.environ.get("TV_MAC", "aa:bb:cc:dd:ee:ff")
POWER_ON_PHRASES = {"power on", "turn on", "switch on", "on"}
POWER_OFF_PHRASES = {"power off", "turn off", "switch off", "shut down", "off"}


def tv_is_on():
    # the TV only accepts connections on its remote-control port when it is on
    body = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        '<s:Body><u:GetVolume xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">'
        '<InstanceID>0</InstanceID><Channel>Master</Channel>'
        '</u:GetVolume></s:Body></s:Envelope>'
    )
    req = urllib.request.Request(
        "http://%s:9197/upnp/control/RenderingControl1" % TV_IP,
        data=body.encode(),
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": '"urn:schemas-upnp-org:service:RenderingControl:1#GetVolume"',
        },
    )
    try:
        socket.create_connection((TV_IP, 8002), timeout=3).close()
        return True
    except Exception:
        return False


def wake_tv():
    # Wake-on-LAN magic packet (needs "Power On with Mobile" enabled on the TV)
    mac = bytes.fromhex(TV_MAC.replace(":", ""))
    pkt = bytes([0xFF]) * 6 + mac * 16
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for addr in ("192.168.0.255", "255.255.255.255", TV_IP):
            for port in (7, 9):
                s.sendto(pkt, (addr, port))
    finally:
        s.close()


def set_power(want_on):
    # Turn the TV and the Sky Q box on or off. Each part is independent, so one
    # failing (e.g. TV already off) does not stop the other.
    result = {}
    try:
        on_now = tv_is_on()
        if want_on:
            if on_now:
                result["tv"] = "already on"
            else:
                wake_tv()
                result["tv"] = "ok"
        else:
            if on_now:
                send_tv_keys(["KEY_POWER"], linger=3)
                result["tv"] = "ok"
            else:
                result["tv"] = "already off"
    except Exception as e:
        log.error("TV power failed: %s", e)
        result["tv"] = "failed: " + str(e)
    try:
        remote = get_sky()
        try:
            status = str(remote.power_status()).upper()
        except Exception:
            status = None
        if status is None:
            remote.press(["power"])
            result["sky"] = "power pressed (state unknown)"
        else:
            is_on = status not in ("STANDBY", "OFF")
            if is_on == want_on:
                result["sky"] = "already " + ("on" if is_on else "off")
            else:
                remote.press(["power"])
                result["sky"] = "ok"
    except Exception as e:
        log.error("Sky power failed: %s", e)
        result["sky"] = "failed: " + str(e)
    return result


SAVED_VOLUME_FILE = os.environ.get("SAVED_VOLUME_FILE", "/home/pi/saved-volume.json")
SAVED_VOLUME_MAX_AGE = 3600  # seconds; older saved levels are ignored
RESTORE_PHRASES = {"play", "volume back", "restore volume", "call finished", "back to normal"}


def load_saved_volume():
    try:
        with open(SAVED_VOLUME_FILE) as f:
            data = json.load(f)
        if time.time() - data["time"] > SAVED_VOLUME_MAX_AGE:
            clear_saved_volume()
            return None
        return int(data["volume"])
    except Exception:
        return None


def save_volume(level):
    with open(SAVED_VOLUME_FILE, "w") as f:
        json.dump({"volume": level, "time": time.time()}, f)


def clear_saved_volume():
    try:
        os.remove(SAVED_VOLUME_FILE)
    except OSError:
        pass


def get_tv_volume():
    body = (
        '<?xml version="1.0"?>'
        '<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        '<s:Body><u:GetVolume xmlns:u="urn:schemas-upnp-org:service:RenderingControl:1">'
        '<InstanceID>0</InstanceID><Channel>Master</Channel>'
        '</u:GetVolume></s:Body></s:Envelope>'
    )
    req = urllib.request.Request(
        "http://%s:9197/upnp/control/RenderingControl1" % TV_IP,
        data=body.encode(),
        headers={
            "Content-Type": 'text/xml; charset="utf-8"',
            "SOAPAction": '"urn:schemas-upnp-org:service:RenderingControl:1#GetVolume"',
        },
    )
    text = urllib.request.urlopen(req, timeout=5).read().decode()
    m = re.search("<CurrentVolume>([0-9]+)</CurrentVolume>", text)
    if not m:
        raise RuntimeError("could not read TV volume")
    return int(m.group(1))


def silence_tv():
    # remember the current level (unless one is already saved from this call), then go to 0
    if load_saved_volume() is None:
        current = get_tv_volume()
        if current > 0:
            save_volume(current)
    set_tv_volume(0)


def restore_tv_volume():
    saved = load_saved_volume()
    if saved is None:
        return None
    set_tv_volume(saved)
    clear_saved_volume()
    return saved


SKY_PAUSED_FILE = os.environ.get("SKY_PAUSED_FILE", "/home/pi/sky-paused.flag")


def clear_sky_flag():
    try:
        os.remove(SKY_PAUSED_FILE)
    except OSError:
        pass


def pause_sky():
    # In apps (e.g. Netflix) the play key toggles and pause does nothing;
    # on live TV / recordings pause works. Remember that we paused it.
    clear_sky_flag()
    try:
        remote = get_sky()
        if str(remote.power_status()).upper() in ("STANDBY", "OFF"):
            return "standby, not touched"
        app = remote.get_active_application()
        key = "play" if app else "pause"
        remote.press([key])
        with open(SKY_PAUSED_FILE, "w") as f:
            f.write(str(time.time()))
        return "sent " + key
    except Exception as e:
        log.error("Phone: could not pause Sky box: %s", e)
        return "failed: " + str(e)


def resume_sky():
    try:
        with open(SKY_PAUSED_FILE) as f:
            paused_at = float(f.read())
    except Exception:
        return False
    clear_sky_flag()
    if time.time() - paused_at > SAVED_VOLUME_MAX_AGE:
        return False
    try:
        get_sky().press(["play"])
        return True
    except Exception as e:
        log.error("Could not resume Sky box: %s", e)
        return False


# If set, a "phone" call is also passed on to another room's service
# (e.g. http://127.0.0.1:8081/command). Only the bedroom service sets it.
FORWARD_PHONE_URL = os.environ.get("FORWARD_PHONE_URL", "")


def forward_phone():
    if not FORWARD_PHONE_URL:
        return

    def _send():
        try:
            req = urllib.request.Request(
                FORWARD_PHONE_URL,
                data=json.dumps({"phrase": "phone"}).encode(),
                headers={"Content-Type": "application/json"},
            )
            urllib.request.urlopen(req, timeout=20).read()
            log.info("Forwarded phone call to %s", FORWARD_PHONE_URL)
        except Exception as e:
            log.error("Could not forward phone call: %s", e)

    threading.Thread(target=_send, daemon=True).start()


@app.route("/health")
def health():
    """Simple check that the server is up - doesn't touch the Sky Q box."""
    return jsonify({"status": "ok"})


@app.route("/command", methods=["POST"])
def command():
    """
    Main endpoint the Siri Shortcut calls.
    Expects JSON: {"phrase": "channel up"}
    """
    data = request.get_json(silent=True) or {}
    phrase = str(data.get("phrase", "")).strip().lower()

    if not phrase:
        return jsonify({"error": "No phrase provided"}), 400

    if phrase == "phone":
        forward_phone()
        out = {"phrase": phrase}
        first_ring = load_saved_volume() is None
        try:
            silence_tv()
            out["tv"] = "silenced"
        except Exception as e:
            log.error("Phone: could not silence TV: %s", e)
            out["tv"] = "failed: " + str(e)
        if first_ring:
            out["sky"] = pause_sky()
        else:
            out["sky"] = "already handled this call"
        log.info("Phone call -> %s", out)
        out["success"] = True
        return jsonify(out)

    if phrase in RESTORE_PHRASES:
        try:
            restored = restore_tv_volume()
            if restored is not None:
                log.info("Restored TV volume to %d", restored)
                if phrase == "play" and resume_sky():
                    log.info("Resumed Sky box")
        except Exception as e:
            log.error("Could not restore TV volume: %s", e)
            restored = None
        if phrase != "play" or restored is not None:
            return jsonify({"success": True, "phrase": phrase, "restored_volume": restored})

    if phrase in POWER_ON_PHRASES or phrase in POWER_OFF_PHRASES:
        want_on = phrase in POWER_ON_PHRASES
        res = set_power(want_on)
        log.info("Power %s -> %s", phrase, res)
        any_ok = any(not v.startswith("failed") for v in res.values())
        out = {"success": any_ok, "phrase": phrase}
        out.update(res)
        return jsonify(out), (200 if any_ok else 500)

    level = parse_set_volume(phrase)
    if level is not None:
        if not 0 <= level <= MAX_SET_VOLUME:
            return jsonify({"error": "Volume must be 0 to %d" % MAX_SET_VOLUME}), 400
        try:
            set_tv_volume(level)
            clear_saved_volume()
            log.info("Set TV volume: %s -> %d", phrase, level)
            return jsonify({"success": True, "phrase": phrase, "volume": level})
        except Exception as e:
            log.error("Failed to set TV volume %r: %s", phrase, e)
            return jsonify({"error": "TV not reachable: " + str(e)}), 500

    tv_keys = tv_command(phrase)
    if tv_keys:
        try:
            send_tv_keys(tv_keys)
            log.info("Sent TV command: %s -> %s", phrase, tv_keys)
            return jsonify({"success": True, "phrase": phrase, "tv_keys": tv_keys})
        except Exception as e:
            log.error("Failed to send TV command %r: %s", phrase, e)
            return jsonify({"error": "TV not reachable: " + str(e)}), 500

    key = COMMAND_MAP.get(phrase)
    if key is None:
        key = repeat_key(phrase)
    if key is None:
        log.warning("Unrecognised phrase: %r", phrase)
        return jsonify({"error": f"Unrecognised phrase: {phrase}"}), 400

    try:
        remote = get_sky()
        remote.press(key if isinstance(key, list) else [key])
        log.info("Sent command: %s -> %s", phrase, key)
        return jsonify({"success": True, "phrase": phrase, "key": key})
    except Exception as e:
        log.error("Failed to send command %r: %s", phrase, e)
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    # host="0.0.0.0" so it's reachable from other devices (Sharon's iPad) on the network
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=False)
