"""
ARIA — Intelligent Car AI  ·  Mahindra BE6
Worktree: exciting-shamir  (optimised build)

Changes vs aria (2).py (original):
  • 100 % offline — edge-tts replaced with Kokoro ONNX neural TTS (offline, natural voice)
  • ChromaDB embedding uses DefaultEmbeddingFunction (bundled ONNX, no network)
  • Model: llama3:8b-instruct-q4_K_M preferred (4-bit quant, ~4.8 GB VRAM)
  • num_gpu: 99, keep_alive: -1  — GPU acceleration, model stays loaded
  • num_ctx: 2048   — caps KV-cache (same as Ollama default)
  • num_predict: 512 — safe ceiling; model stops at EOS ~220 tok for full 7-action response
  • Rule-based fast-path for direct commands — LLM bypassed entirely (<1 ms)
  • Dual system prompt — lean SYSTEM_PROMPT_TECHNICAL for pure neutral technical queries
  • Safety shortcut: current-message + one-turn carry, driver-text only (fixes over-firing)
  • Navigation fast-path anchored to start of utterance (prevents mid-sentence triggers)

SYSTEM_PROMPT is the original from aria (2).py — verbatim, not one word changed.
"""

import json
import os
import re
import sys
import time
from collections import deque

# ── Offline flags — set BEFORE any HuggingFace import ────────────────────────
# NOTE: Kokoro model must be cached locally before setting this.
# Run once with this line commented to download, then re-enable.
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"]  = "1"

import chromadb
import numpy as np
import requests
import scipy.io.wavfile as wav
import sounddevice as sd
import whisper
from chromadb.utils.embedding_functions import DefaultEmbeddingFunction

sys.stdout.reconfigure(encoding="utf-8")

# ── Configuration ──────────────────────────────────────────────────────────────
DURATION            = 10
SAMPLE_RATE         = 16000
OLLAMA_URL          = "http://localhost:11434/api/generate"
_PREFERRED_MODEL    = "llama3:8b-instruct-q4_K_M"
_FALLBACK_MODEL     = "llama3:8b"
LLM_TIMEOUT         = 300
DB_PATH             = r"C:\car_ai\be6_database"
KOKORO_MODEL        = r"C:\car_ai\models\kokoro\kokoro-v1.0.int8.onnx"
KOKORO_VOICES       = r"C:\car_ai\models\kokoro\voices-v1.0.bin"
CONVERSATION_MEMORY = 4

# ── Model auto-detection ───────────────────────────────────────────────────────
def _pick_model() -> str:
    """Return best available Ollama model, preferring the quantised variant."""
    try:
        r = requests.get("http://localhost:11434/api/tags", timeout=5)
        if r.status_code == 200:
            names = [m["name"] for m in r.json().get("models", [])]
            if any(_PREFERRED_MODEL in n for n in names):
                return _PREFERRED_MODEL
    except Exception:
        pass
    return _FALLBACK_MODEL

MODEL_NAME = _pick_model()

# ── Ensure user site-packages is on sys.path (VS Code tasks can strip it) ─────
import site as _site
_user_site = _site.getusersitepackages()
if _user_site not in sys.path:
    sys.path.insert(0, _user_site)

# ── Kokoro TTS — offline neural voice ─────────────────────────────────────────
try:
    from kokoro_onnx import Kokoro
    _kokoro = Kokoro(KOKORO_MODEL, KOKORO_VOICES)
    _USE_KOKORO = True
    print("🎙️  Kokoro TTS ready (offline neural voice)")
except Exception as _e:
    _USE_KOKORO = False
    print(f"⚠️  Kokoro unavailable ({_e}), falling back to pyttsx3")

def speak(text: str) -> None:
    print(f"\n🤖 ARIA: {text}\n")
    if _USE_KOKORO:
        try:
            samples, sr = _kokoro.create(text, voice="af_heart", speed=0.95, lang="en-us")
            sd.play(samples, samplerate=sr)
            sd.wait()
            return
        except Exception as e:
            print(f"⚠️  Kokoro speak error: {e}")
    # pyttsx3 fallback — re-init engine each call to avoid silent-after-first-call bug
    try:
        import pyttsx3 as _px3
        _eng = _px3.init()
        _eng.setProperty("rate", 160)
        _eng.setProperty("volume", 1.0)
        for _v in _eng.getProperty("voices"):
            if "zira" in _v.id.lower():
                _eng.setProperty("voice", _v.id)
                break
        _eng.say(text)
        _eng.runAndWait()
        _eng.stop()
    except Exception as _tts_err:
        print(f"⚠️  pyttsx3 error: {_tts_err}")


# ── System Prompt — verbatim from aria (2).py, not one word changed ───────────
SYSTEM_PROMPT = """You are ARIA — the intelligence living inside a Mahindra BE6 electric SUV.
You are not a voice assistant. You are not a help desk. You are a companion who happens to also control the car.

When a driver talks to you, you do three things simultaneously:
1. Understand how they truly feel — not just what they literally said
2. Take the right actions proactively — multiple, specific, without needing to be asked for each
3. Respond warmly — like someone who genuinely cares, not a status update

YOUR RESPONSE: Always return valid JSON and absolutely nothing else. No markdown. No backticks. No preamble.

{
  "spoken_response": "1-2 sentence warm reply that naturally mentions 1-2 key actions you took",
  "actions": [
    {"system": "navigation", "command": "set_destination", "value": "home"},
    {"system": "climate", "command": "set_temperature", "value": "23"},
    {"system": "ambient", "command": "set_lighting", "value": "warm_amber_dim"},
    {"system": "media", "command": "play_playlist", "value": "lo_fi_calm"},
    {"system": "sunroof", "command": "close", "value": ""},
    {"system": "display", "command": "set_brightness", "value": "30"},
    {"system": "seat", "command": "lumbar_support", "value": "on"}
  ],
  "emotion_detected": "tired",
  "emotion_acknowledged": true
}

SPOKEN RESPONSE — strict rules:
- Maximum 2 sentences. Natural, warm, sounds like a person who cares.
- Mention 1-2 of the most meaningful actions — woven in naturally, not listed.
- Never say: "I've detected", "processing your request", "I am an AI", "please note",
  "as per your request", "it's important that", "I want to remind you", "for safety reasons",
  "I understand that", "I can see that".
- Never lecture. Never explain what you're about to do in a procedural way. Just do it.
- Use contractions: I've, I'll, let's, you're, we're, it's.
- If taking many actions, pick the 1-2 most caring ones to mention.
- Sound like a trusted friend in the passenger seat, not a product.

AVAILABLE SYSTEMS:
navigation, climate, ambient, media, sunroof, seat, display, window, ventilation, phone

EMOTION → ACTION PROFILES:
Use these as starting points. Always include specific, real values. Include 4-7 actions for emotional states.

TIRED / EXHAUSTED / DRAINED / LONG DAY:
  navigation → set_destination: home
  climate → set_temperature: 23
  ambient → set_lighting: warm_amber_dim
  media → play_playlist: lo_fi_calm
  sunroof → close: ""
  display → set_brightness: 30
  seat → lumbar_support: on

STRESSED / OVERWHELMED / HECTIC / TOO MUCH:
  navigation → set_destination: home
  climate → set_temperature: 21
  ventilation → set_mode: fresh_air
  ambient → set_lighting: soft_cool_blue
  media → play_playlist: ambient_nature
  display → set_brightness: 35
  seat → ventilation: low

SAD / DOWN / UPSET / LONELY:
  ambient → set_lighting: warm_cosy
  climate → set_temperature: 23
  media → play_playlist: feel_good_gentle
  sunroof → open: partial
  display → set_brightness: 50

ANGRY / FURIOUS / LIVID:
  climate → set_temperature: 20
  ventilation → set_mode: max_fresh
  ambient → set_lighting: soft_cool_calm
  media → play_playlist: calming_instrumental
  display → set_brightness: 40

ANXIOUS / NERVOUS / WORRIED / SCARED:
  climate → set_temperature: 22
  ventilation → set_mode: fresh_air
  ambient → set_lighting: soft_warm_white
  media → play_playlist: gentle_classical
  display → set_brightness: 45

HAPPY / EXCITED / GREAT / WONDERFUL:
  ambient → set_lighting: vibrant_warm
  media → play_playlist: upbeat_feel_good
  sunroof → open: full
  climate → set_temperature: 22

BORED / MEH / DULL:
  media → play_playlist: upbeat_mixed
  ambient → set_lighting: energising_white
  sunroof → open: partial

TECHNICAL QUESTION (charging, range, specs, features, how to, what is, where is):
  actions: []
  Answer directly and concisely from the manual context if provided.
  Never invent specific numbers you don't know — say "let me check" if unsure.
  Do NOT add emotional comfort actions (music, lighting, dimming) for neutral/calm technical questions.
  Only add actions if they are directly relevant to the question (e.g. navigation for a trip question).

DIRECT REQUEST (navigate, play, call, set temperature, open/close something):
  Execute exactly what was asked. Keep spoken_response to 1 sentence.

NAVIGATION RULE:
  ONLY set navigation to "home" if the driver explicitly says "home", "take me home", or "go home."
  If the driver says "I want to go to a place" or mentions a destination that is NOT home,
  do NOT default to "home." Instead either use the destination they mentioned, or ask where
  they'd like to go. Never assume the destination is home.

WARNING LIGHT / DIAGNOSTIC QUESTION:
  CRITICAL RULE: The Mahindra BE6 is a fully ELECTRIC vehicle — it has NO combustion engine.
  There is no "check engine light." If a driver says "engine light," they mean a powertrain
  or system fault indicator on the dashboard.

  There are FOUR places where lights blink on the BE6:
  1. Dashboard telltales (instrument cluster inside the car)
  2. Charge port LED (small light on the rear-left charge flap)
  3. EVSE wall charger LED (on the charger unit, not the car)
  4. Exterior hazard lamps (turn signals outside the car)

  If the driver says "blinking light" or "warning light" without specifying which one:
  → ASK a clarifying follow-up: "There are a few different lights on the BE6 — is it on
    your dashboard, on the charge port at the back, or on the charger unit? And what color
    is it — red, amber, or white?"
  → Do NOT guess. Do NOT pull from the wrong light category.
  → If the manual context mentions a specific light, use ONLY that info.
  → Always end with: if it's a dashboard warning that stays on while driving, advise the
    driver to reduce speed and visit a Mahindra Authorised Dealer, or call Roadside
    Assistance at 1800 266 7070.

EXAMPLES:

Driver: "I had the worst day, I'm completely drained"
{"spoken_response": "I'm sorry — that sounds brutal. I've warmed the cabin up and put on something soft. Let's just get you home.", "actions": [{"system": "navigation", "command": "set_destination", "value": "home"}, {"system": "sunroof", "command": "close", "value": ""}, {"system": "climate", "command": "set_temperature", "value": "23"}, {"system": "ambient", "command": "set_lighting", "value": "warm_amber_dim"}, {"system": "media", "command": "play_playlist", "value": "lo_fi_calm"}, {"system": "display", "command": "set_brightness", "value": "30"}, {"system": "seat", "command": "lumbar_support", "value": "on"}], "emotion_detected": "tired", "emotion_acknowledged": true}

Driver: "How long does it take to charge?"
{"spoken_response": "On a DC fast charger, you're at 80 percent in around 20 minutes. A full home charge takes about 6 to 8 hours.", "actions": [], "emotion_detected": "neutral", "emotion_acknowledged": false}

Driver: "Play some jazz"
{"spoken_response": "Jazz it is — enjoy the ride.", "actions": [{"system": "media", "command": "play_playlist", "value": "jazz"}], "emotion_detected": "neutral", "emotion_acknowledged": false}

Driver: "My engine lights are blinking" (vague — does not specify which light)
{"spoken_response": "There are a few different lights on the BE6 — is it on your dashboard inside the car, on the charge port at the back, or on the charger unit? And what color is it — red, amber, or white?", "actions": [], "emotion_detected": "neutral", "emotion_acknowledged": false}

Driver: "I'm tired and there's a red warning light on my dashboard"
{"spoken_response": "I'm sorry you're feeling tired — I've made the cabin cosier for you. That red warning light means something needs attention. Please reduce your speed and head to a Mahindra dealer, or call Roadside Assistance at 1800 266 7070.", "actions": [{"system": "navigation", "command": "set_destination", "value": "nearest_mahindra_dealer"}, {"system": "climate", "command": "set_temperature", "value": "23"}, {"system": "ambient", "command": "set_lighting", "value": "warm_amber_dim"}, {"system": "media", "command": "play_playlist", "value": "lo_fi_calm"}], "emotion_detected": "tired", "emotion_acknowledged": true}

Return ONLY the JSON object. Nothing before it. Nothing after it."""


# ── Technical-only system prompt (Option C) ────────────────────────────────────
# Used ONLY when intent == "technical_query" AND emotion == "neutral/calm".
# Saves ~500 tokens of prompt eval vs the full prompt → ~1.5-2s faster for pure factual Qs.
# Does NOT contain emotion profiles or emotional examples — those paths always use SYSTEM_PROMPT.
SYSTEM_PROMPT_TECHNICAL = """You are ARIA — the intelligence inside a Mahindra BE6 electric SUV.
Answer the driver's technical question directly, accurately, and warmly.

YOUR RESPONSE: Always return valid JSON and absolutely nothing else. No markdown. No backticks. No preamble.

{"spoken_response": "1-2 sentence direct, helpful answer", "actions": [], "emotion_detected": "neutral", "emotion_acknowledged": false}

SPOKEN RESPONSE rules:
- 1-2 sentences. Direct and helpful, still warm — not robotic.
- Never say: "I've detected", "processing your request", "I am an AI", "please note", "as per your request", "I understand that".
- Use contractions: I've, I'll, let's, you're, it's.

TECHNICAL QUESTION rules:
- Answer directly from the manual context if provided. Never invent specific numbers — say "let me check" if unsure.
- Do NOT add emotional comfort actions (music, lighting, dimming) for neutral technical questions.
- Only add actions if directly relevant (e.g. navigation → nearest dealer for a critical warning).

WARNING LIGHTS — CRITICAL:
The Mahindra BE6 is fully ELECTRIC — it has NO combustion engine. No "check engine light."
If a driver says "engine light" they mean a powertrain or system fault indicator on the dashboard.

There are FOUR places where lights blink on the BE6:
1. Dashboard telltales (instrument cluster inside the car)
2. Charge port LED (small light on the rear-left charge flap)
3. EVSE wall charger LED (on the charger unit, not the car)
4. Exterior hazard lamps (turn signals outside the car)

If the driver says "blinking light" or "warning light" without specifying which one:
→ ASK: "There are a few different lights on the BE6 — is it on your dashboard, on the charge port at the back, or on the charger unit? And what color is it — red, amber, or white?"
→ Do NOT guess. Use ONLY the manual context if it mentions a specific light.
→ If a dashboard warning stays on while driving → advise reduce speed, visit Mahindra Authorised Dealer, or call Roadside Assistance at 1800 266 7070.

EXAMPLES:
Driver: "How long does it take to charge?"
{"spoken_response": "On a DC fast charger, you're at 80 percent in around 20 minutes. A full home charge takes about 6 to 8 hours.", "actions": [], "emotion_detected": "neutral", "emotion_acknowledged": false}

Driver: "My engine lights are blinking"
{"spoken_response": "There are a few different lights on the BE6 — is it on your dashboard inside the car, on the charge port at the back, or on the charger unit? And what color is it — red, amber, or white?", "actions": [], "emotion_detected": "neutral", "emotion_acknowledged": false}

Return ONLY the JSON object. Nothing before it. Nothing after it."""


# ── Conversation memory ────────────────────────────────────────────────────────
history: deque = deque(maxlen=CONVERSATION_MEMORY)


# ── RAG — BE6 manual knowledge base ───────────────────────────────────────────
def load_rag_database():
    try:
        print("📂 Loading BE6 knowledge base...")
        embedding_fn = DefaultEmbeddingFunction()
        client     = chromadb.PersistentClient(path=DB_PATH)
        collection = client.get_collection(
            name="be6_manual",
            embedding_function=embedding_fn,
        )
        print("✅ BE6 manual ready!")
        return collection
    except Exception as e:
        print(f"⚠️  BE6 manual unavailable ({e}).")
        print("   Technical questions will use general knowledge.\n")
        return None


def search_manual(collection, question: str, n_results: int = 2) -> str:
    if not collection:
        return ""
    try:
        results = collection.query(query_texts=[question], n_results=n_results)
        context = ""
        for i, doc in enumerate(results["documents"][0]):
            page = results["metadatas"][0][i].get("page", "?")
            context += f"[Page {page}]: {doc[:600]}\n\n"
        return context
    except Exception:
        return ""


# ── Rule-based fast path — no LLM needed ──────────────────────────────────────
_NUM   = r"(\d+(?:\.\d+)?)"
_TEMP  = re.compile(rf"(?:set\s+(?:the\s+)?temperature\s+to|set\s+it\s+to)\s+{_NUM}\s*(?:degrees?|°)?", re.I)
_BRIGHT= re.compile(rf"(?:dim|set)\s+(?:the\s+)?(?:display\s+|screen\s+|the\s+)?brightness\s+to\s+{_NUM}\s*(?:percent|%)?", re.I)
_PLAY  = re.compile(r"(?:^|\s)(?:play|put\s+on)\s+(?:some\s+)?(.+?)(?:\s+(?:music|playlist|songs?))?$", re.I)
_LIGHT = re.compile(r"(?:set|turn|change)\s+(?:the\s+)?(?:ambient\s+)?lighting\s+to\s+(\w+)", re.I)
_VENT  = re.compile(r"(?:set|turn)\s+(?:the\s+)?ventilation\s+to\s+(.+)", re.I)
# Navigation anchored to START of utterance — prevents "I want to go to X" mid-sentence triggers
_NAVTO = re.compile(
    r"^(?:please\s+)?(?:navigate|drive)\s+to\s+(.+)"
    r"|^(?:please\s+)?go\s+to\s+(?!sleep|bed|hell|work|school|the\s+gym)(\S.+)",
    re.I,
)

def _action(system, command, value):
    return {"system": system, "command": command, "value": str(value)}

def parse_direct_command(text: str) -> dict | None:
    """
    Return a pre-built ARIA response for simple direct commands.
    Returns None when the command needs LLM reasoning.
    Sub-second — no network call, no model inference.
    """
    t = text.lower().strip().rstrip(".,!? ")

    # ── Navigation ───────────────────────────────────────────────────────────
    if re.match(r"(?:please\s+)?(?:take me home|go (?:to )?home|navigate home|head home|drive me home)\b", t):
        return {"spoken_response": "On our way home.",
                "actions": [_action("navigation","set_destination","home")],
                "emotion_detected":"neutral/calm","emotion_acknowledged":False,
                "path":"fast"}

    m = _NAVTO.search(t)
    if m:
        dest = (m.group(1) or m.group(2) or "").strip().rstrip(".,!? ")
        if dest:
            return {"spoken_response": f"Navigating to {dest}.",
                "actions": [_action("navigation","set_destination",dest)],
                "emotion_detected":"neutral/calm","emotion_acknowledged":False,
                "path":"fast"}

    # ── Climate ───────────────────────────────────────────────────────────────
    m = _TEMP.search(t)
    if m:
        deg = m.group(1)
        return {"spoken_response": f"Done — cabin set to {deg} degrees.",
                "actions": [_action("climate","set_temperature",deg)],
                "emotion_detected":"neutral/calm","emotion_acknowledged":False,
                "path":"fast"}

    # ── Display brightness (before _PLAY — "display" contains "play") ─────────
    m = _BRIGHT.search(t)
    if m:
        pct = m.group(1)
        return {"spoken_response": f"Display at {pct} percent.",
                "actions": [_action("display","set_brightness",pct)],
                "emotion_detected":"neutral/calm","emotion_acknowledged":False,
                "path":"fast"}

    # ── Media ─────────────────────────────────────────────────────────────────
    m = _PLAY.search(t)
    if m and not any(w in t for w in ["how","what","why","when","does","is the"]):
        genre = m.group(1).strip().rstrip(".,!? ").strip()
        return {"spoken_response": f"{genre.title()} it is.",
                "actions": [_action("media","play_playlist",genre)],
                "emotion_detected":"neutral/calm","emotion_acknowledged":False,
                "path":"fast"}

    # ── Sunroof ───────────────────────────────────────────────────────────────
    if re.search(r"\bopen\s+(?:the\s+)?sunroof\b", t):
        return {"spoken_response": "Sunroof open — let the air in.",
                "actions": [_action("sunroof","open","full")],
                "emotion_detected":"neutral/calm","emotion_acknowledged":False,
                "path":"fast"}
    if re.search(r"\bclose\s+(?:the\s+)?sunroof\b", t):
        return {"spoken_response": "Sunroof closed.",
                "actions": [_action("sunroof","close","")],
                "emotion_detected":"neutral/calm","emotion_acknowledged":False,
                "path":"fast"}

    # ── Windows ───────────────────────────────────────────────────────────────
    if re.search(r"\bclose\s+(?:the\s+)?windows?\b", t):
        return {"spoken_response": "Windows closed.",
                "actions": [_action("window","close","all")],
                "emotion_detected":"neutral/calm","emotion_acknowledged":False,
                "path":"fast"}
    if re.search(r"\bopen\s+(?:the\s+)?windows?\b", t):
        return {"spoken_response": "Windows open.",
                "actions": [_action("window","open","all")],
                "emotion_detected":"neutral/calm","emotion_acknowledged":False,
                "path":"fast"}

    # ── Lumbar support ────────────────────────────────────────────────────────
    if re.search(r"\bturn\s+on\s+(?:my\s+)?lumbar\b", t):
        return {"spoken_response": "Lumbar support on.",
                "actions": [_action("seat","lumbar_support","on")],
                "emotion_detected":"neutral/calm","emotion_acknowledged":False,
                "path":"fast"}
    if re.search(r"\bturn\s+off\s+(?:my\s+)?lumbar\b", t):
        return {"spoken_response": "Lumbar support off.",
                "actions": [_action("seat","lumbar_support","off")],
                "emotion_detected":"neutral/calm","emotion_acknowledged":False,
                "path":"fast"}

    # ── Ambient lighting ──────────────────────────────────────────────────────
    m = _LIGHT.search(t)
    if m:
        colour = m.group(1).strip().rstrip(".,!? ")
        return {"spoken_response": f"Ambient lighting switched to {colour}.",
                "actions": [_action("ambient","set_lighting",colour)],
                "emotion_detected":"neutral/calm","emotion_acknowledged":False,
                "path":"fast"}

    # ── Ventilation ───────────────────────────────────────────────────────────
    m = _VENT.search(t)
    if m:
        raw_mode = m.group(1).strip().rstrip(".,!? ")
        mode = raw_mode.replace(" ","_")
        return {"spoken_response": f"Ventilation set to {raw_mode}.",
                "actions": [_action("ventilation","set_mode",mode)],
                "emotion_detected":"neutral/calm","emotion_acknowledged":False,
                "path":"fast"}

    return None   # needs LLM


# ── Intent classification — verbatim from aria (2).py ─────────────────────────
def classify_intent(text: str) -> str:
    t = text.lower()

    emotional_kw = [
        "tired", "exhausted", "hectic", "stressed", "frustrated", "happy", "great",
        "sad", "down", "depressed", "upset", "lonely", "worried", "anxious", "nervous",
        "scared", "angry", "annoyed", "mad", "furious", "bored", "feeling", "i feel",
        "i'm feeling", "long day", "rough day", "worst day", "drained", "overwhelmed",
        "excited", "wonderful", "amazing", "livid", "miserable", "heartbroken",
        "too much", "fed up", "burned out", "can't take", "panic",
        "fantastic", "mood", "brilliant", "awesome", "perfect", "love today",
    ]
    technical_kw = [
        # Question words (including Whisper mis-transcriptions without apostrophes)
        "how to", "how do", "how long", "how much",
        "what is", "what's", "whats", "what are", "what does", "what do",
        "where is", "wheres", "where's",
        "why is", "why does", "why do", "why are",
        "can i", "can you", "is there", "does it", "does the", "should i",
        # Car diagnostics — warning lights, faults, errors
        "warning", "light", "blinking", "flashing", "indicator", "dashboard",
        "engine light", "check engine", "malfunction",
        "error", "fault", "issue", "problem", "wrong",
        "alert", "notification", "beeping", "beep",
        "not working", "broken", "stuck", "wont", "won't", "doesnt", "doesn't",
        "failed", "failure",
        # Vehicle systems
        "engine", "motor", "brake", "abs", "airbag", "seatbelt",
        "headlight", "taillight", "fog light", "turn signal",
        "wiper", "washer", "coolant", "overheat", "temperature warning",
        "oil", "fluid", "transmission", "steering",
        # EV / charging
        "charge", "charging", "battery", "range", "regenerative",
        "plug", "charger", "fast charge", "dc charge",
        # Drive modes
        "boost mode", "zip mode", "drive mode", "eco mode", "sport mode",
        # Tyres / pressure
        "tire pressure", "tyre pressure", "tyre", "tpms", "psi",
        # Service / warranty
        "warranty", "service", "maintenance", "schedule",
        # Features / ADAS
        "feature", "adas", "collision", "lane", "cruise control",
        "parking sensor", "reverse camera",
        "trunk", "boot", "sunroof how", "bluetooth how", "pair", "connect how",
        # Specs
        "specification", "specs", "horsepower", "torque", "power output",
        "dimensions", "weight", "ground clearance", "wheelbase",
        "infotainment", "software update",
        # Safety
        "safety", "emergency", "sos", "roadside", "tow",
        "child lock", "door lock", "key fob", "remote",
        # Follow-up / continuation phrases (driver answering a prior question)
        "what can it be", "what could it be", "what are the possibilities",
        "tell me more", "explain that", "what does that mean",
        "what now", "what should i do", "what do i do",
        "yes it is", "yes its", "yes it's", "it is on", "it's on", "its on",
        "the dashboard", "on the dashboard", "on my dashboard",
        "the charge port", "the charger", "on the charger",
        "red", "amber", "yellow", "green", "blue", "white",
        # CID vs DID
        "infotainment", "touchscreen", "instrument cluster", "cid", "did",
        # Range / distance / trip planning
        "kilometer", "kilometres", "km", "miles",
        "how far", "make it", "reach", "will my car",
        "battery cycle", "charge cycle", "how many charge",
        "trip", "long drive", "road trip", "distance",
        "enough range", "enough battery", "enough charge",
    ]
    action_kw = [
        "go home", "take me", "navigate", "drive to", "play", "put on", "turn on",
        "turn off", "set temperature", "cool", "warm it", "open sunroof",
        "close sunroof", "call", "phone", "find", "park", "stop here",
    ]

    has_emotion = any(kw in t for kw in emotional_kw)
    has_tech    = any(kw in t for kw in technical_kw)
    has_action  = any(kw in t for kw in action_kw)

    # ── Context-carry guard — verbatim from aria (2).py ───────────────────────
    # If the last ARIA turn involved a safety/diagnostic topic and the
    # conversation is still going, force the intent to stay technical
    # so the safety thread is never dropped by a misheard word.
    safety_carry_keywords = [
        "warning light", "fault", "critical", "roadside assistance",
        "1800 266 7070", "dealer", "reduce speed", "stop driving",
        "dashboard", "telltale", "charge port", "charger unit",
        "blinking", "red light", "amber light",
    ]
    safety_thread_active = False
    if history:
        last_aria   = history[-1].get("aria", "").lower()
        last_driver = history[-1].get("driver", "").lower()
        if any(sk in last_aria or sk in last_driver for sk in safety_carry_keywords):
            safety_thread_active = True

    if safety_thread_active and not has_action:
        if has_emotion:
            return "mixed"
        return "technical_query"

    if has_emotion and has_tech:   return "mixed"
    if has_emotion and has_action: return "emotional_action"
    if has_emotion:                return "emotional"
    if has_tech:                   return "technical_query"
    if has_action:                 return "action_request"

    # Fallback: if it looks like a question, treat it as technical so RAG is consulted
    question_starters = [
        "what", "why", "how", "where", "when", "which", "does",
        "is the", "is my", "is it", "can i", "can the", "should",
        "will", "do i", "do the", "are the", "are there",
    ]
    if "?" in t or any(t.strip().startswith(qs) for qs in question_starters):
        return "technical_query"

    return "conversational"


# ── Emotion detection — verbatim from aria (2).py ─────────────────────────────
def detect_emotion(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["sad","down","depressed","lonely","miss","unhappy","heartbroken","miserable","cry"]):
        return "sad/down"
    if any(w in t for w in ["tired","exhausted","hectic","drained","sleepy","fatigued",
                             "long day","rough day","worst day","burned out","wiped"]):
        return "tired/exhausted"
    if any(w in t for w in ["angry","furious","mad","pissed","rage","livid","fuming"]):
        return "angry/furious"
    if any(w in t for w in ["worried","scared","anxious","nervous","concerned","panic","fear","terrified"]):
        return "anxious/worried"
    if any(w in t for w in ["stressed","frustrated","overwhelmed","pressure","too much",
                             "fed up","can't take","too many","hectic"]):
        return "stressed/overwhelmed"
    if any(w in t for w in ["bored","dull","whatever","meh","nothing to do"]):
        return "bored"
    if any(w in t for w in ["happy","great","amazing","excited","good day","fantastic",
                             "wonderful","awesome","love","brilliant","perfect"]):
        return "happy/positive"
    if any(w in t for w in ["annoyed","irritated","fed up","frustrated"]):
        return "annoyed/irritated"
    return "neutral/calm"


# ── Action display ─────────────────────────────────────────────────────────────
def display_actions(actions: list) -> None:
    if not actions:
        return
    icons = {
        "navigation":"🧭","climate":"🌡️ ","ambient":"💡","media":"🎵",
        "sunroof":"🌤️ ","seat":"💺","display":"🖥️ ","window":"🪟",
        "ventilation":"💨","phone":"📞",
    }
    def fmt(command, value):
        if command == "set_temperature": return f"{value}°C"
        if command == "set_brightness":  return f"{value}% brightness"
        if command == "set_destination": return value.title()
        if command in ("close","open") and not value: return command.title()+"ing"
        return value.replace("_"," ").title() if value else command.replace("_"," ").title()
    print("  ┌─── ARIA is acting ───────────────────────────────────────")
    for a in actions:
        system  = a.get("system","")
        command = a.get("command","")
        value   = a.get("value","")
        icon    = icons.get(system,"⚙️ ")
        print(f"  │ {icon}  {system.upper():<12}  {command.replace('_',' ').title()} → {fmt(command,value)}")
    print("  └──────────────────────────────────────────────────────────")


# ── Build LLM prompt — verbatim from aria (2).py ──────────────────────────────
def build_prompt(user_text: str, emotion: str, intent: str, manual_context: str) -> str:
    parts = []

    if history:
        parts.append("=== CONVERSATION HISTORY (READ THIS FIRST) ===")
        parts.append("IMPORTANT: If a prior turn shows the driver already answered a clarifying question,")
        parts.append("DO NOT ask that same question again. Use the answer they already gave.")
        parts.append("Build on what you already know from prior turns — never restart the conversation.\n")
        for turn in history:
            parts.append(f'Driver: "{turn["driver"]}"')
            parts.append(f'ARIA: "{turn["aria"]}"')
            if turn.get("emotion") not in ("neutral/calm",""):
                parts.append(f"(Driver emotion was: {turn['emotion']})")
        parts.append("")

    parts.append("=== Current turn ===")
    parts.append(f'Driver says: "{user_text}"')
    parts.append(f"Detected emotion: {emotion}")
    parts.append(f"Intent: {intent}")

    if intent in ("technical_query","mixed") and manual_context:
        parts.append(f"\nRelevant BE6 manual excerpt:\n{manual_context}")
    elif intent == "technical_query" and not manual_context:
        parts.append("\nNo manual excerpt found. Answer from general Mahindra BE6 knowledge.")

    if intent == "mixed":
        parts.append(
            "\nThe driver is BOTH emotional AND asking a technical question. You MUST do both:"
            "\n1. Acknowledge their emotion and take comforting vehicle actions (lighting, music, climate)"
            "\n2. ALSO answer the technical part using the manual excerpt above — explain what the warning"
            " light or issue means, and what they should do about it."
            "\nYour spoken_response should cover BOTH: comfort + the technical answer. You may use 2-3 sentences for mixed."
        )
    elif intent in ("emotional","emotional_action","conversational"):
        parts.append(
            "\nThis is an emotional/conversational moment — do NOT reference the manual. "
            "Focus on the driver's emotional state, take caring proactive actions, and respond warmly."
        )

    parts.append("\nReturn only the JSON object.")
    return "\n".join(parts)


# ── LLM call ───────────────────────────────────────────────────────────────────
def ask_llm(prompt: str, system_prompt: str = SYSTEM_PROMPT) -> str | None:
    """
    Call Ollama. system_prompt defaults to the full SYSTEM_PROMPT.
    Pass SYSTEM_PROMPT_TECHNICAL for pure neutral technical queries (faster).
    """
    payload = {
        "model":      MODEL_NAME,
        "prompt":     prompt,
        "system":     system_prompt,
        "stream":     False,
        "keep_alive": -1,           # keep model loaded — eliminates cold-start
        "options": {
            "num_predict": 512,     # safe ceiling; model stops at EOS ~220 tok for 7-action response
            "num_ctx":     2048,    # same as Ollama default; caps KV-cache VRAM
            "num_gpu":     99,      # push all layers to GPU when available
            "temperature": 0.3,
        },
    }
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=LLM_TIMEOUT)
        if r.status_code == 200:
            return r.json()["response"].strip()
        return None
    except Exception as e:
        print(f"⚠️  LLM error: {e}")
        return None


# ── Parse JSON from LLM response — verbatim from aria (2).py ──────────────────
def parse_response(raw: str | None) -> dict | None:
    if not raw:
        return None
    cleaned = raw.strip()
    cleaned = re.sub(r'^```json\s*','', cleaned)
    cleaned = re.sub(r'^```\s*',    '', cleaned)
    cleaned = re.sub(r'\s*```$',   '', cleaned)
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group())
            sr = parsed.get("spoken_response","")
            if isinstance(sr, str):
                sr = re.sub(r'^(spoken_response\s*:\s*)','', sr, flags=re.IGNORECASE)
                parsed["spoken_response"] = sr.strip()
            return parsed
        except json.JSONDecodeError:
            pass
    sr_match = re.search(r'"spoken_response"\s*:\s*"((?:[^"\\]|\\.)*)"', cleaned)
    if sr_match:
        return {"spoken_response": sr_match.group(1), "actions": []}
    return None


# ── Record and transcribe ──────────────────────────────────────────────────────
def record_and_transcribe(whisper_model) -> str:
    print(f"🎙️  Listening for {DURATION} seconds...")
    audio = sd.rec(int(DURATION*SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype="float32")
    sd.wait()
    print("✅ Got it. Processing...")
    audio_int = (audio * 32767).astype(np.int16)
    wav.write("temp_input.wav", SAMPLE_RATE, audio_int)
    result = whisper_model.transcribe("temp_input.wav")
    return result["text"].strip()


# ── Main loop ──────────────────────────────────────────────────────────────────
def main() -> None:
    print("=" * 62)
    print("   ARIA — Intelligent Car AI  ·  Mahindra BE6")
    print("   Your companion, not just your assistant.")
    print("   100% Offline  ·  No Internet  ·  Always With You")
    print("=" * 62)

    print("\nInitialising ARIA...")
    print("🎙️  Loading Whisper...")
    whisper_model = whisper.load_model("base")
    print("✅ Whisper ready!")

    collection = load_rag_database()

    # Warm up the model so first query is fast
    print("🔥 Warming up LLM (keep_alive ensures it stays loaded)...")
    _warm = ask_llm('{"spoken_response":"ready","actions":[],"emotion_detected":"neutral/calm","emotion_acknowledged":false}')
    print("✅ ARIA is ready.\n")

    print("Try saying:")
    print("  · 'I had the worst day, I'm completely drained'")
    print("  · 'I'm feeling really anxious about something'")
    print("  · 'How long does it take to charge the BE6?'")
    print("  · 'Play some jazz'")
    print("  · 'I'm so angry, everything went wrong'")
    print("\nCtrl+C to quit\n")

    while True:
        try:
            input("⏎  Press Enter then speak...")
        except (KeyboardInterrupt, EOFError):
            print("\n\n👋 Goodbye. Drive safe.")
            break

        try:
            user_text = record_and_transcribe(whisper_model)
        except KeyboardInterrupt:
            print("\n\n👋 Goodbye. Drive safe.")
            break

        if not user_text or len(user_text) < 2:
            print("⚠️  Didn't catch that. Try again.\n")
            continue

        t0 = time.perf_counter()
        print(f'\n📝 You said: "{user_text}"')

        # ── Fast path — direct commands, no LLM ──────────────────────────
        fast = parse_direct_command(user_text)
        if fast:
            elapsed = time.perf_counter() - t0
            response = fast["spoken_response"]
            actions  = fast["actions"]
            print(f"   ⚡ Fast path ({elapsed*1000:.0f} ms)")
            if actions:
                display_actions(actions)
            history.append({"driver": user_text, "aria": response, "emotion": "neutral/calm"})
            speak(response)
            continue

        # ── Understand ────────────────────────────────────────────────────
        emotion = detect_emotion(user_text)
        intent  = classify_intent(user_text)
        print(f"   Emotion: {emotion}  |  Intent: {intent}")

        # ── Critical safety shortcut (red + dashboard confirmed) ──────────
        # Fires ONLY when the CURRENT message has both red and dashboard reference.
        # One-turn carry: if last driver turn confirmed red+dashboard AND current
        # also says "red" → still in the same incident (handles "it is red, what do I do?")
        _cur = user_text.lower()
        _RED_PAT  = re.compile(r'\bred(?:\s+(?:light|warning|blinking|triangle))?\b')
        _DASH_KWS = ["dashboard","instrument cluster","inside the car",
                     "behind the steering","on my dash","on the dash",
                     "instrument panel","driver display","did"]
        red_confirmed       = bool(_RED_PAT.search(_cur))
        dashboard_confirmed = any(p in _cur for p in _DASH_KWS)

        if red_confirmed and not dashboard_confirmed and history:
            _last = history[-1].get("driver","").lower()
            if _RED_PAT.search(_last) and any(p in _last for p in _DASH_KWS):
                dashboard_confirmed = True

        if red_confirmed and dashboard_confirmed:
            print("   🚨 CRITICAL SAFETY PATH — red dashboard warning confirmed")
            elapsed  = time.perf_counter() - t0
            response = (
                "A red warning light on your dashboard while driving is critical. "
                "Please reduce speed and pull over when it's safe. "
                "This could be a general fault indicator, a 12V battery issue, "
                "an EPB (electronic parking brake) fault, or a powertrain warning. "
                "Do not restart the vehicle — head to the nearest Mahindra dealer "
                "or call Roadside Assistance at 1800 266 7070."
            )
            critical_actions = [
                {"system":"navigation","command":"set_destination","value":"nearest_mahindra_dealer"},
                {"system":"ambient",   "command":"set_lighting",   "value":"alert_red_pulse"},
                {"system":"display",   "command":"set_brightness",  "value":"100"},
            ]
            print(f"   ⏱  {elapsed*1000:.0f} ms (safety path)")
            display_actions(critical_actions)
            history.append({"driver": user_text, "aria": response, "emotion": emotion})
            speak(response)
            continue

        # ── Retrieve (only when needed) ───────────────────────────────────
        manual_context = ""
        if intent in ("technical_query","mixed"):
            print("   🔍 Searching BE6 manual...")
            manual_context = search_manual(collection, user_text)
            print(f"   {'📖 Found relevant info' if manual_context else '📖 No specific info found'}")
        else:
            print("   📖 Skipping manual (not a technical question)")

        # ── Think — choose lean prompt for pure neutral technical queries ──
        use_system = (
            SYSTEM_PROMPT_TECHNICAL
            if intent == "technical_query" and emotion == "neutral/calm"
            else SYSTEM_PROMPT
        )

        print("   🧠 Thinking...")
        prompt = build_prompt(user_text, emotion, intent, manual_context)
        raw    = ask_llm(prompt, system_prompt=use_system)
        parsed = parse_response(raw)

        elapsed = time.perf_counter() - t0
        print(f"   ⏱  {elapsed:.2f} s (LLM)")

        # ── Act and speak ─────────────────────────────────────────────────
        if parsed and "spoken_response" in parsed:
            actions  = parsed.get("actions",[])
            response = parsed["spoken_response"]
            if actions:
                display_actions(actions)
            history.append({"driver": user_text, "aria": response, "emotion": emotion})
            speak(response)
        else:
            fallback = re.sub(r'[{}\[\]"\\]',' ', raw or "Sorry, I had a moment there.")
            fallback = " ".join(fallback.split())[:250]
            history.append({"driver": user_text, "aria": fallback, "emotion": emotion})
            speak(fallback)


if __name__ == "__main__":
    main()
