"""RoomPet: stateful pet moods + Arduino serial + Claude dialogue + Roomba Wi-Fi.

Runs on macOS or Raspberry Pi. See run commands in the accompanying reply.
Arduino sends zone changes: NEAR (5-50 cm), INTERACTING (<=5 cm), GONE (>50 cm).
Only these distance zones are available: physical touch cannot be distinguished.
"""

import argparse
from collections import deque
import html
import os
from pathlib import Path
import queue
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

# ---- Adjust behavior here -------------------------------------------------
GONE_HAPPY_GRACE_SECONDS = 5      # short "I'll miss you" phase after leaving play
NEAR_WITHOUT_PETTING_SECONDS = 30 # near without interaction -> SAD
SAD_TO_ANGRY_SECONDS = 30         # stay near while SAD -> ANGRY
IGNORED_SECONDS = 180             # continuously GONE for 3 min -> upset cycle
ABANDONED_ANGRY_SECONDS = 12      # alternate angry / sad during long absence
ABANDONED_SAD_SECONDS = 6
ANGER_COOLDOWN_SECONDS = 15       # space needed before anger can be forgiven
SUSTAINED_PETTING_SECONDS = 10    # 7-12 s sustained INTERACTING -> ANGRY
PETTING_WINDOW_SECONDS = 30
PETTING_LIMIT = 4                 # 4 quick distinct touches -> ANGRY
PLAY_BREAK_SECONDS = 4           # 4 s at NEAR between touches clears touch count
MAX_HISTORY = 8                    # FIFO history; oldest item removed when full
AI_MAX_TOKENS = 1024
MODEL = os.getenv("AI_MODEL", "claude-haiku-5-5")
SCRIPT_DIR = Path(__file__).resolve().parent
VALID_ZONES = {"NEAR", "INTERACTING", "GONE"}

PERSONA = """You are RoomPet, a playful, expressive robot pet. You detect distance, not touch.
Your owner can play by moving very close, then backing away to NEAR (5-50 cm).
Mood is decided by the controller, not you. Write ONLY one playful message (at most 15 words)
that fits the provided mood, situation and recent history. No mood label, markdown or reasoning."""


class PetBrain:
    """Time-based, deterministic emotions driven by Arduino zone transitions.

    NEAR never makes RoomPet happy on its own. INTERACTING is the only
    action that can switch it from SAD to HAPPY. Continuous INTERACTING
    is counted by time in tick(), not by repeated serial messages.
    """

    def __init__(self, now=None):
        now = time.monotonic() if now is None else now
        self.zone = "GONE"
        self.zone_since = now
        self.current_time = now
        self.mood = "SAD"  # no pretend greeting before the first real interaction
        self.reason = "Come play with me!"
        self.history = deque(maxlen=MAX_HISTORY)
        self.pets = deque()
        self.last_pet = None
        self.gone_since = None  # begins on a real Arduino GONE message
        self.sad_since = None
        self.anger_reason = None  # "overpet", "neglect", "absence"
        self.cooldown_from = None
        self.recovery_ready = False
        self.last_movement = float("-inf")
        self.revision = 0

    def _set_mood(self, mood, reason, anger_reason=None):
        if self.mood == mood and self.reason == reason:
            return False
        previous = self.mood
        self.mood, self.reason = mood, reason
        self.revision += 1
        if mood == "SAD" and previous != "SAD":
            self.sad_since = self.current_time
        elif mood != "SAD":
            self.sad_since = None
        if mood == "ANGRY":
            self.anger_reason = anger_reason or self.anger_reason
            self.recovery_ready = False if self.zone != "GONE" else self.recovery_ready
            self.cooldown_from = self.current_time if self.zone == "GONE" else None
        elif mood == "HAPPY":
            self.anger_reason = None
            self.recovery_ready = False
            self.cooldown_from = None
        return True

    def update(self, zone, now=None):
        now = time.monotonic() if now is None else now
        self.current_time = now
        if zone not in VALID_ZONES or zone == self.zone:
            return False
        previous = self.zone
        old_duration = now - self.zone_since

        # Distinct pokes only; a constant reading in INTERACTING counts as one.
        if previous == "NEAR" and old_duration >= PLAY_BREAK_SECONDS:
            self.pets.clear()

        self.zone = zone
        self.zone_since = now
        self.history.append(zone)
        # Invalidate pending dialogue even when the mood stays the same.
        self.revision += 1

        if zone == "GONE":
            self.gone_since = now
            self.pets.clear()
            if self.mood == "ANGRY" and self.anger_reason != "absence":
                self.cooldown_from = now
            if self.mood == "HAPPY":
                return self._set_mood("HAPPY", "I'll wait a moment for you!")
            return False

        # Approaching alone never earns happiness. Interrupt angry cooldown.
        if previous == "GONE" and self.gone_since is not None:
            if now - self.gone_since >= ANGER_COOLDOWN_SECONDS:
                self.recovery_ready = True
        self.gone_since = None

        if zone == "NEAR":
            if self.mood == "SAD" and self.sad_since is None:
                self.sad_since = now
            self.cooldown_from = None
            if self.mood == "ANGRY" and self.recovery_ready:
                return self._set_mood("SAD", "I'm still upset. Will you play with me?")
            return False

        # INTERACTING: only this may turn SAD into HAPPY.
        self.cooldown_from = None
        if self.mood == "ANGRY" and not self.recovery_ready:
            return False
        if self.mood == "ANGRY" and self.recovery_ready:
            self.pets.clear()
            self.anger_reason = None
            return self._set_mood("HAPPY", "Okay, I forgive you! Let's play!")

        self.last_pet = now
        self.pets.append(now)
        while self.pets and now - self.pets[0] > PETTING_WINDOW_SECONDS:
            self.pets.popleft()
        if len(self.pets) >= PETTING_LIMIT:
            return self._set_mood("ANGRY", "Stop poking me so much!", "overpet")
        return self._set_mood("HAPPY", "Yes! Let's play together!")

    def tick(self, now=None):
        now = time.monotonic() if now is None else now
        self.current_time = now
        duration = now - self.zone_since

        if self.zone == "INTERACTING":
            if self.mood == "HAPPY" and duration >= SUSTAINED_PETTING_SECONDS:
                return self._set_mood("ANGRY", "That's too much petting! Give me space!", "overpet")
            # Time-based touch detection works even with NO serial activity.
            return False

        if self.zone == "NEAR":
            if self.mood == "ANGRY":
                return False
            if self.mood == "HAPPY" and duration >= NEAR_WITHOUT_PETTING_SECONDS:
                return self._set_mood("SAD", "You're here, but you're not playing with me.")
            if self.mood == "SAD" and self.sad_since is not None:
                if now - self.sad_since >= SAD_TO_ANGRY_SECONDS:
                    return self._set_mood("ANGRY", "You're close but ignoring me!", "neglect")
            return False

        # GONE. For a few seconds after play, keep HAPPY, then become SAD.
        if self.gone_since is None:
            return False
        gone_duration = now - self.gone_since

        # Extended absence is a repeating ANGRY -> SAD -> ANGRY cycle.
        # The cycle is NOT cancelled by the 15-second cooldown while still away.
        if gone_duration >= IGNORED_SECONDS:
            cycle = ABANDONED_ANGRY_SECONDS + ABANDONED_SAD_SECONDS
            phase = (gone_duration - IGNORED_SECONDS) % cycle
            if phase < ABANDONED_ANGRY_SECONDS:
                return self._set_mood("ANGRY", "Where are you?! I wanted attention!", "absence")
            return self._set_mood("SAD", "I miss you... please come back.")

        if self.mood == "ANGRY":
            if self.anger_reason != "absence" and gone_duration >= ANGER_COOLDOWN_SECONDS:
                self.recovery_ready = True
                return self._set_mood("SAD", "I've calmed down. Come play with me.")
            return False

        if self.mood == "HAPPY" and gone_duration >= GONE_HAPPY_GRACE_SECONDS:
            return self._set_mood("SAD", "You left! I miss you already.")
        return False

    def should_move(self, now=None):
        now = time.monotonic() if now is None else now
        if self.zone != "INTERACTING" or self.mood != "HAPPY":
            return False
        if now - self.last_movement < MOVEMENT_COOLDOWN_SECONDS:
            return False
        self.last_movement = now
        return True


class RoombaControl:
    """Serialize Wi-Fi actions. Send one command per mood transition.

    Commands may be delayed or fail; the Roomba's own safety system remains
    responsible for navigation. This is not an emergency-stop system.
    """

    ACTIONS = {"HAPPY": "clean", "SAD": "stop", "GRUMPY": "stop", "ANGRY": "dock"}

    def __init__(self, enabled):
        self.enabled = enabled
        self.target = None
        self.pending = queue.Queue(maxsize=1)
        self.closed = threading.Event()
        self.worker = None
        if enabled:
            self.worker = threading.Thread(target=self._run, daemon=True)
            self.worker.start()

    def set_mood(self, mood):
        action = self.ACTIONS.get(mood)
        if not self.enabled or not action or action == self.target:
            return
        self.target = action
        # Discard obsolete queued commands; never interrupt an in-flight one.
        try:
            while True:
                self.pending.get_nowait()
        except queue.Empty:
            pass
        self.pending.put_nowait(action)
        print(f"Roomba target ({mood}): {action.upper()}", flush=True)

    def _run(self):
        while not self.closed.is_set():
            try:
                action = self.pending.get(timeout=0.2)
            except queue.Empty:
                continue
            # If a newer mood arrived, do not send the stale command.
            if action != self.target:
                continue
            try:
                result = subprocess.run(
                    ["node", str(SCRIPT_DIR / "roomba.js"), action],
                    cwd=SCRIPT_DIR, capture_output=True, text=True,
                    timeout=20, check=True,
                )
                print(f"Roomba sent: {action.upper()}", flush=True)
            except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
                detail = (getattr(exc, "stderr", "") or "").strip()
                print(f"Roomba {action} FAILED: {detail or exc}", flush=True)

    def shutdown(self):
        self.closed.set()
        # Do not override docking on program exit. If cleaning, a stop is
        # best-effort; command completion cannot be guaranteed.
        if self.enabled and self.target == "clean":
            try:
                subprocess.run(
                    ["node", str(SCRIPT_DIR / "roomba.js"), "stop"],
                    cwd=SCRIPT_DIR, capture_output=True, text=True, timeout=10,
                )
            except (OSError, subprocess.TimeoutExpired):
                pass


latest = {"mood": "SAD", "message": "Come play with me!", "time": ""}
latest_lock = threading.Lock()


class Page(BaseHTTPRequestHandler):
    def do_GET(self):
        with latest_lock:
            mood = html.escape(latest["mood"])
            message = html.escape(latest["message"])
            stamp = html.escape(latest["time"])
        body = f'''<!doctype html><html><head><meta charset="utf-8">
        <meta http-equiv="refresh" content="2"><meta name="viewport" content="width=device-width,initial-scale=1">
        <title>RoomPet</title></head><body style="font-family:sans-serif;text-align:center;padding:15vh 1rem">
        <h1>{mood}</h1><p style="font-size:1.5rem">{message}</p><small>{stamp}</small>
        </body></html>'''.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


def start_server():
    server = ThreadingHTTPServer(("0.0.0.0", 8000), Page)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("Dashboard: http://localhost:8000", flush=True)
    return server


def ask_ai(mood, situation, recent):
    key = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is missing")
    prompt = (f"Mood: {mood}\nSituation: {situation}\nRecent zones: {', '.join(recent)}\n"
              "Reply with only a short dialogue line fitting the mood.")
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    for max_tokens in (AI_MAX_TOKENS, AI_MAX_TOKENS * 2):
        response = requests.post(
            "https://api.anthropic.com/v1/messages", headers=headers,
            json={"model": MODEL, "max_tokens": max_tokens, "system": PERSONA,
                  "messages": [{"role": "user", "content": prompt}]}, timeout=45,
        )
        if not response.ok:
            raise RuntimeError(f"Anthropic HTTP {response.status_code}: {response.text[:250]}")
        data = response.json()
        reply = " ".join(
            block.get("text", "") for block in data.get("content", [])
            if isinstance(block, dict) and block.get("type") == "text"
        ).strip()
        if reply:
            return reply.splitlines()[0][:200]
        if data.get("stop_reason") != "max_tokens":
            raise ValueError(f"AI returned no text: {data.get('stop_reason')}")
    raise ValueError("AI returned no text despite retry")


class DialogueWorker:
    """AI runs in background so time-based moods and Arduino serial don't freeze."""

    def __init__(self):
        self.jobs = queue.Queue(maxsize=1)
        threading.Thread(target=self._run, daemon=True).start()

    def schedule(self, brain):
        job = (brain.revision, brain.mood, brain.reason, tuple(brain.history))
        try:
            self.jobs.put_nowait(job)
        except queue.Full:
            try:
                self.jobs.get_nowait()
            except queue.Empty:
                pass
            self.jobs.put_nowait(job)

    def _run(self):
        while True:
            revision, mood, situation, recent = self.jobs.get()
            try:
                message = ask_ai(mood, situation, recent)
            except Exception as exc:
                print(f"AI dialogue unavailable: {type(exc).__name__}: {exc}", flush=True)
                continue
            with latest_lock:
                if latest.get("revision") == revision:
                    latest["message"] = message
                    print(f"AI says ({mood}): {message}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="RoomPet with emotion rules")
    ap.add_argument("--port", default=os.getenv("PET_PORT"), help="Arduino serial port")
    ap.add_argument("--list-ports", action="store_true")
    ap.add_argument("--test-ai", action="store_true")
    ap.add_argument("--no-movement", action="store_true")
    args = ap.parse_args()
    if args.list_ports:
        from serial.tools import list_ports
        for port in list_ports.comports():
            print(f"{port.device} — {port.description}")
        return
    if args.test_ai:
        for mood, reason in (("HAPPY", "Playing"), ("SAD", "Not playing"), ("ANGRY", "Too much petting")):
            print(mood, "->", ask_ai(mood, reason, ["NEAR", "INTERACTING"]))
        return
    if not args.port:
        ap.error("Provide --port DEVICE (or use --list-ports)")

    enabled = not args.no_movement
    if enabled and (not (SCRIPT_DIR / "roomba.js").is_file() or
                    not all(os.getenv(x) for x in ("ROOMBA_IP", "ROOMBA_BLID", "ROOMBA_PASSWORD"))):
        enabled = False
        print("Roomba movement disabled: missing roomba.js or credentials", flush=True)
    roomba = RoombaControl(enabled)
    brain = PetBrain()
    dialogue = DialogueWorker()

    import serial
    server = None
    try:
        with serial.Serial(args.port, 9600, timeout=0.25) as arduino:
            time.sleep(2)
            arduino.reset_input_buffer()
            server = start_server()
            print(f"RoomPet ready on {args.port}; movement={'ON' if enabled else 'OFF'}", flush=True)

            # Apply the initial mood (SAD => STOP) when movement is enabled.
            last_mood = None

            def sync_movement():
                nonlocal last_mood
                if brain.mood != last_mood:
                    last_mood = brain.mood
                    roomba.set_mood(brain.mood)

            def publish():
                with latest_lock:
                    latest.update(mood=brain.mood, message=brain.reason,
                                  revision=brain.revision, time=time.strftime("%H:%M:%S"))
                arduino.write((brain.mood + "\n").encode("ascii"))
                arduino.flush()
                print(f"AI says ({brain.mood}): {brain.reason}", flush=True)
                dialogue.schedule(brain)
                sync_movement()

            sync_movement()
            while True:
                raw = arduino.readline().decode(errors="replace").strip()
                if raw:
                    zone = raw.removeprefix("Zone changed:").strip().upper()
                    if zone in VALID_ZONES:
                        print(f"Arduino event: {zone}", flush=True)
                        changed = brain.update(zone)
                        if changed:
                            publish()
                        else:
                            with latest_lock:
                                latest.update(mood=brain.mood, message=brain.reason,
                                              revision=brain.revision, time=time.strftime("%H:%M:%S"))
                            print(f"AI says ({brain.mood}): {brain.reason}", flush=True)
                            dialogue.schedule(brain)
                            sync_movement()
                    elif "ERROR" not in raw.upper():
                        print("Arduino:", raw, flush=True)
                if brain.tick():
                    publish()

    except KeyboardInterrupt:
        print("RoomPet stopped.")
    except serial.SerialException as exc:
        print(f"Arduino serial error: {exc}")
    finally:
        roomba.shutdown()
        if server:
            server.shutdown()


if __name__ == "__main__":
    main()
