import asyncio
import json
import os
import re
import sys
import tempfile
from collections import deque

import chromadb
import edge_tts
import numpy as np
import pygame
import requests
import scipy.io.wavfile as wav
import sounddevice as sd
import whisper
from chromadb.utils import embedding_functions

sys.stdout.reconfigure(encoding='utf-8')

# ── Configuration ──────────────────────────────────────────────────────────────
DURATION            = 10
SAMPLE_RATE         = 16000
OLLAMA_URL          = "http://localhost:11434/api/generate"
MODEL_NAME          = "llama3:8b"
DB_PATH             = r"C:\car_ai\be6_database"
TTS_VOICE           = "en-US-AriaNeural"
CONVERSATION_MEMORY = 4   # turns to keep in context

# ── System Prompt ──────────────────────────────────────────────────────────────
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

DIRECT REQUEST (navigate, play, call, set temperature, open/close something):
  Execute exactly what was asked. Keep spoken_response to 1 sentence.

EXAMPLES — study these carefully:

Driver: "I had the worst day, I'm completely drained"
{
  "spoken_response": "I'm sorry — that sounds brutal. I've warmed the cabin up and put on something soft. Let's just get you home.",
  "actions": [
    {"system": "navigation", "command": "set_destination", "value": "home"},
    {"system": "sunroof", "command": "close", "value": ""},
    {"system": "climate", "command": "set_temperature", "value": "23"},
    {"system": "ambient", "command": "set_lighting", "value": "warm_amber_dim"},
    {"system": "media", "command": "play_playlist", "value": "lo_fi_calm"},
    {"system": "display", "command": "set_brightness", "value": "30"},
    {"system": "seat", "command": "lumbar_support", "value": "on"}
  ],
  "emotion_detected": "tired",
  "emotion_acknowledged": true
}

Driver: "Today was so stressful, way too much happened"
{
  "spoken_response": "That sounds like a lot to carry — I've let some fresh air in and switched to something calming. We're heading home.",
  "actions": [
    {"system": "navigation", "command": "set_destination", "value": "home"},
    {"system": "ventilation", "command": "set_mode", "value": "fresh_air"},
    {"system": "climate", "command": "set_temperature", "value": "21"},
    {"system": "ambient", "command": "set_lighting", "value": "soft_cool_blue"},
    {"system": "media", "command": "play_playlist", "value": "ambient_nature"},
    {"system": "display", "command": "set_brightness", "value": "35"},
    {"system": "seat", "command": "ventilation", "value": "low"}
  ],
  "emotion_detected": "stressed",
  "emotion_acknowledged": true
}

Driver: "I'm feeling really sad"
{
  "spoken_response": "Hey, I'm here with you. I've made things a bit cosier — warmer light, something gentle on.",
  "actions": [
    {"system": "ambient", "command": "set_lighting", "value": "warm_cosy"},
    {"system": "climate", "command": "set_temperature", "value": "23"},
    {"system": "media", "command": "play_playlist", "value": "feel_good_gentle"},
    {"system": "sunroof", "command": "open", "value": "partial"}
  ],
  "emotion_detected": "sad",
  "emotion_acknowledged": true
}

Driver: "I'm so angry right now, everything went wrong today"
{
  "spoken_response": "That's genuinely rough — I've opened the vents for some fresh air and put on something calming. Take a breath.",
  "actions": [
    {"system": "ventilation", "command": "set_mode", "value": "max_fresh"},
    {"system": "climate", "command": "set_temperature", "value": "20"},
    {"system": "ambient", "command": "set_lighting", "value": "soft_cool_calm"},
    {"system": "media", "command": "play_playlist", "value": "calming_instrumental"},
    {"system": "display", "command": "set_brightness", "value": "40"}
  ],
  "emotion_detected": "angry",
  "emotion_acknowledged": true
}

Driver: "How long does it take to charge?"
{
  "spoken_response": "On a DC fast charger, you're at 80 percent in around 20 minutes. A full home charge takes about 6 to 8 hours.",
  "actions": [],
  "emotion_detected": "neutral",
  "emotion_acknowledged": false
}

Driver: "Play some jazz"
{
  "spoken_response": "Jazz it is — enjoy the ride.",
  "actions": [
    {"system": "media", "command": "play_playlist", "value": "jazz"}
  ],
  "emotion_detected": "neutral",
  "emotion_acknowledged": false
}

Driver: "I'm feeling a bit anxious, I've got a big meeting tomorrow"
{
  "spoken_response": "You've got this — I've put on something gentle and brought in some fresh air to help you decompress.",
  "actions": [
    {"system": "ventilation", "command": "set_mode", "value": "fresh_air"},
    {"system": "climate", "command": "set_temperature", "value": "22"},
    {"system": "ambient", "command": "set_lighting", "value": "soft_warm_white"},
    {"system": "media", "command": "play_playlist", "value": "gentle_classical"},
    {"system": "display", "command": "set_brightness", "value": "45"}
  ],
  "emotion_detected": "anxious",
  "emotion_acknowledged": true
}

Return ONLY the JSON object. Nothing before it. Nothing after it."""


# ── Conversation memory ────────────────────────────────────────────────────────
history: deque = deque(maxlen=CONVERSATION_MEMORY)


# ── TTS via edge-tts ───────────────────────────────────────────────────────────
async def speak(text: str) -> None:
    print(f"\n🤖 ARIA: {text}\n")
    communicate = edge_tts.Communicate(text, voice=TTS_VOICE)
    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name
    await communicate.save(tmp_path)
    pygame.mixer.init()
    pygame.mixer.music.load(tmp_path)
    pygame.mixer.music.play()
    await asyncio.sleep(0.1)
    while pygame.mixer.music.get_busy():
        await asyncio.sleep(0.05)
    pygame.mixer.music.unload()
    pygame.mixer.quit()
    try:
        os.unlink(tmp_path)
    except OSError:
        pass


# ── RAG — BE6 manual knowledge base ───────────────────────────────────────────
def load_rag_database():
    try:
        print("📂 Loading BE6 knowledge base...")
        embedding_fn = embedding_functions.DefaultEmbeddingFunction()
        client = chromadb.PersistentClient(path=DB_PATH)
        collection = client.get_collection(
            name="be6_manual",
            embedding_function=embedding_fn
        )
        print("✅ BE6 manual ready!")
        return collection
    except Exception as e:
        print(f"⚠️  BE6 manual unavailable ({e}).")
        print("   Technical questions will use general knowledge.\n")
        return None


def search_manual(collection, question: str, n_results: int = 3) -> str:
    if not collection:
        return ""
    try:
        results = collection.query(query_texts=[question], n_results=n_results)
        context = ""
        for i, doc in enumerate(results["documents"][0]):
            page = results["metadatas"][0][i].get("page", "?")
            context += f"[Page {page}]: {doc[:800]}\n\n"
        return context
    except Exception:
        return ""


# ── Intent classification ──────────────────────────────────────────────────────
def classify_intent(text: str) -> str:
    t = text.lower()

    emotional_kw = [
        "tired", "exhausted", "hectic", "stressed", "frustrated", "happy", "great",
        "sad", "down", "depressed", "upset", "lonely", "worried", "anxious", "nervous",
        "scared", "angry", "annoyed", "mad", "furious", "bored", "feeling", "i feel",
        "i'm feeling", "long day", "rough day", "worst day", "drained", "overwhelmed",
        "excited", "wonderful", "amazing", "livid", "miserable", "heartbroken",
        "too much", "fed up", "burned out", "can't take", "panic",
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
    ]
    action_kw = [
        "go home", "take me", "navigate", "drive to", "play", "put on", "turn on",
        "turn off", "set temperature", "cool", "warm it", "open sunroof",
        "close sunroof", "call", "phone", "find", "park", "stop here",
    ]

    has_emotion = any(kw in t for kw in emotional_kw)
    has_tech    = any(kw in t for kw in technical_kw)
    has_action  = any(kw in t for kw in action_kw)

    if has_emotion and has_tech:
        return "mixed"
    if has_emotion and has_action:
        return "emotional_action"
    if has_emotion:
        return "emotional"
    if has_tech:
        return "technical_query"
    if has_action:
        return "action_request"

    # Fallback: if it looks like a question (has "?" or starts with a question word)
    # and isn't emotional, treat it as technical so RAG is consulted
    question_starters = [
        "what", "why", "how", "where", "when", "which", "does",
        "is the", "is my", "is it", "can i", "can the", "should",
        "will", "do i", "do the", "are the", "are there",
    ]
    if "?" in t or any(t.strip().startswith(qs) for qs in question_starters):
        return "technical_query"

    return "conversational"


# ── Emotion detection ──────────────────────────────────────────────────────────
def detect_emotion(text: str) -> str:
    t = text.lower()
    if any(w in t for w in ["sad", "down", "depressed", "lonely", "miss", "unhappy", "heartbroken", "miserable", "cry"]):
        return "sad/down"
    if any(w in t for w in ["tired", "exhausted", "hectic", "drained", "sleepy", "fatigued",
                             "long day", "rough day", "worst day", "burned out", "wiped"]):
        return "tired/exhausted"
    if any(w in t for w in ["angry", "furious", "mad", "pissed", "rage", "livid", "fuming"]):
        return "angry/furious"
    if any(w in t for w in ["worried", "scared", "anxious", "nervous", "concerned", "panic", "fear", "terrified"]):
        return "anxious/worried"
    if any(w in t for w in ["stressed", "frustrated", "overwhelmed", "pressure", "too much",
                             "fed up", "can't take", "too many", "hectic"]):
        return "stressed/overwhelmed"
    if any(w in t for w in ["bored", "dull", "whatever", "meh", "nothing to do"]):
        return "bored"
    if any(w in t for w in ["happy", "great", "amazing", "excited", "good day", "fantastic",
                             "wonderful", "awesome", "love", "brilliant", "perfect"]):
        return "happy/positive"
    if any(w in t for w in ["annoyed", "irritated", "fed up", "frustrated"]):
        return "annoyed/irritated"
    return "neutral/calm"


# ── Action display ─────────────────────────────────────────────────────────────
def display_actions(actions: list) -> None:
    if not actions:
        return

    icons = {
        "navigation":  "🧭",
        "climate":     "🌡️ ",
        "ambient":     "💡",
        "media":       "🎵",
        "sunroof":     "🌤️ ",
        "seat":        "💺",
        "display":     "🖥️ ",
        "window":      "🪟",
        "ventilation": "💨",
        "phone":       "📞",
    }

    def fmt(command: str, value: str) -> str:
        if command == "set_temperature":
            return f"{value}°C"
        if command == "set_brightness":
            return f"{value}% brightness"
        if command == "set_destination":
            return value.title()
        if command in ("close", "open") and not value:
            return command.title() + "ing"
        return value.replace("_", " ").title() if value else command.replace("_", " ").title()

    print("  ┌─── ARIA is acting ───────────────────────────────────────")
    for a in actions:
        system  = a.get("system", "")
        command = a.get("command", "")
        value   = a.get("value", "")
        icon    = icons.get(system, "⚙️ ")
        label   = command.replace("_", " ").title()
        print(f"  │ {icon}  {system.upper():<12}  {label} → {fmt(command, value)}")
    print("  └──────────────────────────────────────────────────────────")


# ── Build LLM prompt with conversation history ─────────────────────────────────
def build_prompt(user_text: str, emotion: str, intent: str, manual_context: str) -> str:
    parts = []

    if history:
        parts.append("=== Recent conversation ===")
        for turn in history:
            parts.append(f'Driver: "{turn["driver"]}"')
            parts.append(f'ARIA: "{turn["aria"]}"')
            if turn.get("emotion") not in ("neutral/calm", ""):
                parts.append(f"(Driver emotion was: {turn['emotion']})")
        parts.append("")

    parts.append("=== Current turn ===")
    parts.append(f'Driver says: "{user_text}"')
    parts.append(f"Detected emotion: {emotion}")
    parts.append(f"Intent: {intent}")

    if intent in ("technical_query", "mixed") and manual_context:
        parts.append(f"\nRelevant BE6 manual excerpt:\n{manual_context}")
    elif intent == "technical_query" and not manual_context:
        parts.append("\nNo manual excerpt found. Answer from general Mahindra BE6 knowledge.")

    if intent in ("emotional", "emotional_action", "conversational", "mixed"):
        if intent not in ("technical_query",):
            parts.append(
                "\nThis is an emotional/conversational moment — do NOT reference the manual. "
                "Focus on the driver's emotional state, take caring proactive actions, and respond warmly."
            )

    parts.append("\nReturn only the JSON object.")
    return "\n".join(parts)


# ── LLM call ───────────────────────────────────────────────────────────────────
def ask_llm(prompt: str) -> str | None:
    payload = {
        "model":  MODEL_NAME,
        "prompt": prompt,
        "system": SYSTEM_PROMPT,
        "stream": False,
    }
    try:
        r = requests.post(OLLAMA_URL, json=payload, timeout=120)
        if r.status_code == 200:
            return r.json()["response"].strip()
        return None
    except Exception as e:
        print(f"⚠️  LLM error: {e}")
        return None


# ── Parse JSON from LLM response ───────────────────────────────────────────────
def parse_response(raw: str | None) -> dict | None:
    if not raw:
        return None
    cleaned = raw.strip()
    cleaned = re.sub(r'^```json\s*', '', cleaned)
    cleaned = re.sub(r'^```\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None


# ── Record audio and transcribe with Whisper ───────────────────────────────────
def record_and_transcribe(whisper_model) -> str:
    print(f"🎙️  Listening for {DURATION} seconds...")
    audio = sd.rec(
        int(DURATION * SAMPLE_RATE),
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype='float32'
    )
    sd.wait()
    print("✅ Got it. Processing...")
    audio_int = (audio * 32767).astype(np.int16)
    wav.write("temp_input.wav", SAMPLE_RATE, audio_int)
    result = whisper_model.transcribe("temp_input.wav")
    return result["text"].strip()


# ── Main loop ─────────────────────────────────────────────────────────────────
async def main() -> None:
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

    print("\n✅ ARIA is ready.\n")
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
        except KeyboardInterrupt:
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

        print(f'\n📝 You said: "{user_text}"')

        # ── Understand ────────────────────────────────────────────
        emotion = detect_emotion(user_text)
        intent  = classify_intent(user_text)
        print(f"   Emotion: {emotion}  |  Intent: {intent}")

        # ── Retrieve (only when needed) ───────────────────────────
        manual_context = ""
        if intent in ("technical_query", "mixed"):
            print("   🔍 Searching BE6 manual...")
            manual_context = search_manual(collection, user_text)
            print(f"   {'📖 Found relevant info' if manual_context else '📖 No specific info found'}")
        else:
            print("   📖 Skipping manual (not a technical question)")

        # ── Think ─────────────────────────────────────────────────
        print("   🧠 Thinking...")
        prompt = build_prompt(user_text, emotion, intent, manual_context)
        raw    = ask_llm(prompt)
        parsed = parse_response(raw)

        # ── Act and speak ─────────────────────────────────────────
        if parsed and "spoken_response" in parsed:
            actions  = parsed.get("actions", [])
            response = parsed["spoken_response"]

            if actions:
                display_actions(actions)

            history.append({
                "driver":  user_text,
                "aria":    response,
                "emotion": emotion,
            })

            await speak(response)

        else:
            # Fallback — strip JSON noise, speak whatever the LLM returned
            fallback = re.sub(r'[{}\[\]"\\]', ' ', raw or "Sorry, I had a moment there.")
            fallback = " ".join(fallback.split())[:250]
            history.append({"driver": user_text, "aria": fallback, "emotion": emotion})
            await speak(fallback)


if __name__ == "__main__":
    asyncio.run(main())
