"""RoomPet: Arduino distance events -> Anthropic mood -> Arduino LEDs.

Works on macOS and Raspberry Pi.

Install (inside a virtual environment):
    python -m pip install requests pyserial

Set your API key IN THE TERMINAL (never paste it into this file):
    export ANTHROPIC_API_KEY="your-key"

Test the AI without an Arduino:
    python pet.py --test-ai

Find serial ports:
    python pet.py --list-ports

Run with Arduino attached (replace the device path):
    python pet.py --port /dev/cu.usbmodem1101  # macOS
    python pet.py --port /dev/ttyACM0        # Raspberry Pi

Open http://localhost:8000 to see the latest reaction.
"""

import argparse
import html
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = os.getenv("AI_MODEL", "claude-haiku-5-5")
BAUD_RATE = 9600
IGNORED_AFTER_SECONDS = 120
VALID_EVENTS = {"NEAR", "INTERACTING", "GONE"}
VALID_MOODS = {"HAPPY", "GRUMPY", "ANGRY", "SAD"}

PERSONA = """You are a small, dramatic desk pet living on someone's desk.
You can only sense distance. Events mean:
NEAR: someone walked up to you.
INTERACTING: someone is very close, almost poking you.
GONE: they walked away.
IGNORED: nobody has come near you for a while.
Possible moods: HAPPY, GRUMPY, ANGRY, SAD.
Pick a mood that fits the recent history. Be funny and in character.
Respond in one line ONLY: MOOD|short message (maximum 15 words).
"""

history = []
latest = {"mood": "...", "message": "Waiting for someone...", "time": ""}


def parse(reply):
    """Validate an AI response before sending the mood to Arduino."""
    mood, separator, message = reply.strip().partition("|")
    mood = mood.strip().upper()
    message = message.strip()
    if not separator or mood not in VALID_MOODS or not message:
        raise ValueError(f"Invalid AI reply format: {reply!r}")
    return mood, message


def ask_ai(event):
    """Get a text response; safely handle non-text content blocks."""
    api_key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY is missing. Set it in your terminal first.")

    recent = ", ".join((history + [event])[-8:])
    prompt = f"Recent events (oldest to newest): {recent}\nNew event: {event}"
    response = requests.post(
        API_URL,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": MODEL,
            "max_tokens": 160,
            "system": PERSONA,
            "messages": [{"role": "user", "content": prompt}],
        },
        timeout=30,
    )
    if not response.ok:
        # Anthropic's error body helps diagnose authentication/model issues.
        raise RuntimeError(f"Anthropic HTTP {response.status_code}: {response.text[:600]}")

    data = response.json()
    texts = [
        block.get("text", "")
        for block in data.get("content", [])
        if isinstance(block, dict) and block.get("type") == "text"
    ]
    reply = "\n".join(texts).strip()
    if not reply:
        block_types = [b.get("type", "unknown") for b in data.get("content", []) if isinstance(b, dict)]
        raise ValueError(
            f"AI returned no text (block types: {block_types}, "
            f"stop_reason: {data.get('stop_reason')}). "
            "Try increasing max_tokens or choosing another model."
        )
    return reply


def react(event):
    """Try the AI, fall back safely on errors, and remember the event."""
    try:
        mood, message = parse(ask_ai(event))
    except (requests.RequestException, ValueError, RuntimeError, KeyError) as exc:
        print(f"AI ERROR ({event}): {type(exc).__name__}: {exc}", flush=True)
        mood, message = "SAD", "My brain is having trouble thinking!"
    history.append(event)
    del history[:-8]
    latest.update(mood=mood, message=message, time=time.strftime("%H:%M:%S"))
    print(f"{event} -> {mood}: {message}", flush=True)
    return mood


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        mood = html.escape(latest["mood"])
        message = html.escape(latest["message"])
        timestamp = html.escape(latest["time"])
        body = f"""<!doctype html><html lang="en"><head>
        <meta charset="utf-8"><meta http-equiv="refresh" content="2">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <title>RoomPet</title></head>
        <body style="font-family:sans-serif;text-align:center;padding:15vh 1rem;background:#fafafa;color:#222">
        <h1>{mood}</h1><p style="font-size:1.5rem">{message}</p><small>{timestamp}</small>
        </body></html>""".encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


def start_web_server():
    server = ThreadingHTTPServer(("0.0.0.0", 8000), Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("Web page: http://localhost:8000", flush=True)
    return server


def show_ports():
    from serial.tools import list_ports
    ports = list(list_ports.comports())
    if not ports:
        print("No serial ports found. Check your USB cable and connection.")
    for port in ports:
        print(f"{port.device} — {port.description}")


def main():
    parser = argparse.ArgumentParser(description="RoomPet AI brain")
    parser.add_argument("--test-ai", action="store_true", help="Test AI events without Arduino")
    parser.add_argument("--list-ports", action="store_true", help="Show available serial ports")
    parser.add_argument("--port", default=os.getenv("PET_PORT"), help="Arduino serial device")
    args = parser.parse_args()

    if args.list_ports:
        show_ports()
        return
    if args.test_ai:
        print("Testing AI without Arduino...", flush=True)
        for event in ("NEAR", "INTERACTING", "GONE"):
            react(event)
        return

    if not args.port:
        print("No serial port selected. Run with --list-ports and then --port DEVICE.")
        return

    import serial
    try:
        with serial.Serial(args.port, BAUD_RATE, timeout=1) as arduino:
            time.sleep(2)  # Opening a USB serial port may reset the Arduino.
            arduino.reset_input_buffer()
            start_web_server()
            print(f"Pet is awake on {args.port} ({BAUD_RATE} baud). Ctrl+C to stop.")
            last_activity = time.monotonic()
            ignored_sent = False

            while True:
                line = arduino.readline().decode("utf-8", errors="replace").strip()
                event = None
                if line:
                    print(f"Arduino sent: {line!r}", flush=True)
                    # Support either plain protocol or the old Arduino debug prefix.
                    candidate = line.removeprefix("Zone changed:").strip().upper()
                    if candidate in VALID_EVENTS:
                        event = candidate
                        last_activity = time.monotonic()
                        ignored_sent = False
                if event is None and not ignored_sent and time.monotonic() - last_activity >= IGNORED_AFTER_SECONDS:
                    event = "IGNORED"
                    ignored_sent = True

                if event:
                    mood = react(event)
                    arduino.write((mood + "\n").encode("ascii"))
                    arduino.flush()

    except KeyboardInterrupt:
        print("\nRoomPet stopped.")
    except serial.SerialException as exc:
        print(f"Serial error: {exc}. Check --port and close Arduino Serial Monitor.")


if __name__ == "__main__":
    main()
