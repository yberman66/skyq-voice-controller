"""
Sky Q Voice Controller
Runs on Pi Zero 2W. Receives commands from Siri Shortcuts (via HTTP POST)
and sends them to a Sky Q box over the local network using pyskyqremote.
"""

import logging
from flask import Flask, request, jsonify
from pyskyqremote.skyq_remote import SkyQRemote

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("skyq-controller")

app = Flask(__name__)

# ---------------------------------------------------------------------------
# CONFIG - fill this in once you know the Sky Q box's IP address on the
# target network (wherever it is installed). pyskyqremote can
# often auto-discover, but a fixed IP is more reliable for a hidden device.
# ---------------------------------------------------------------------------
SKYQ_BOX_IP = "192.168.0.XXX"  # <-- set this to your Sky Q box's IP address

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
}


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

    key = COMMAND_MAP.get(phrase)
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
    # host="0.0.0.0" so it's reachable from other devices (such as an iPad/iPhone) on the network
    app.run(host="0.0.0.0", port=8080, debug=False)
