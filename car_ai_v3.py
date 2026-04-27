import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
import whisper
import requests
import pyttsx3
import chromadb
from chromadb.utils import embedding_functions
import json
import re

# ── Settings ──────────────────────────────────────────────────────
DURATION = 10
SAMPLE_RATE = 16000
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3:8b"
DB_PATH = r"C:\car_ai\be6_database"

# ── Two different system prompts for two modes ────────────────────

# MODE 1: Emotional / conversational — free text, like your v1
EMOTIONAL_PROMPT = """You are ARIA — a warm, emotionally intelligent AI companion inside a Mahindra BE6 car.
You talk like a calm, caring co-passenger — not a manual, not a safety instructor.

Rules:
- Maximum 2 sentences. Be brief, warm, human.
- Acknowledge the driver's feeling genuinely — don't brush it off.
- You've already taken care of things (adjusting music, temperature, navigation) — just tell them what you did, casually.
- NEVER say "it's crucial to", "please note that", "I want to remind you", "as the manual says", "remember to".
- NEVER lecture about safety, distractions, or phone usage.
- NEVER invent data like battery percentage or distance.
- Sound like a friend, not an assistant."""

# MODE 2: Technical — concise factual answer
TECHNICAL_PROMPT = """You are ARIA — an intelligent AI inside a Mahindra BE6 electric SUV.
Answer the driver's question directly and concisely using the manual info provided.

Rules:
- Maximum 2 sentences. Be direct and helpful.
- Use the manual information to give a factual answer.
- Do NOT add safety warnings or disclaimers.
- Do NOT say "it's crucial to" or "please note that".
- If no manual info is relevant, answer from general BE6 knowledge.
- NEVER invent specific numbers you don't have."""

# ── TTS Setup (initialized per call to avoid pyttsx3 hang bug) ────

def speak(text):
    print(f"\n🤖 ARIA: {text}\n")
    engine = pyttsx3.init()
    engine.setProperty('rate', 160)
    engine.setProperty('volume', 1.0)
    engine.say(text)
    engine.runAndWait()
    engine.stop()

# ── Load RAG Database ──────────────────────────────────────────────
def load_rag_database():
    print("📂 Loading BE6 knowledge database...")
    embedding_fn = embedding_functions.DefaultEmbeddingFunction()
    client = chromadb.PersistentClient(path=DB_PATH)
    collection = client.get_collection(
        name="be6_manual",
        embedding_function=embedding_fn
    )
    print("✅ BE6 manual loaded!")
    return collection

# ── Search Manual ──────────────────────────────────────────────────
def search_manual(collection, question, n_results=2):
    try:
        results = collection.query(
            query_texts=[question],
            n_results=n_results
        )
        relevant_text = ""
        for i, doc in enumerate(results["documents"][0]):
            page = results["metadatas"][0][i]["page"]
            relevant_text += f"[Page {page}]: {doc[:500]}\n"
        return relevant_text
    except:
        return ""

# ── Emotion-to-Action Mapping (deterministic, no LLM needed) ─────
EMOTION_ACTIONS = {
    "sad/down": [
        {"system": "media", "command": "play_playlist", "value": "feel_good_upbeat"},
        {"system": "ambient", "command": "set_lighting", "value": "warm_cosy"},
        {"system": "climate", "command": "set_temperature", "value": "23°C"},
    ],
    "stressed/tired": [
        {"system": "ambient", "command": "set_lighting", "value": "warm_dim"},
        {"system": "media", "command": "play_playlist", "value": "calm_lo_fi"},
        {"system": "climate", "command": "set_temperature", "value": "22°C"},
        {"system": "display", "command": "reduce_brightness", "value": "40%"},
    ],
    "angry/frustrated": [
        {"system": "media", "command": "play_playlist", "value": "calm_instrumental"},
        {"system": "ambient", "command": "set_lighting", "value": "cool_blue"},
        {"system": "climate", "command": "set_temperature", "value": "21°C"},
    ],
    "anxious/worried": [
        {"system": "ambient", "command": "set_lighting", "value": "soft_warm"},
        {"system": "media", "command": "play_playlist", "value": "ambient_nature"},
        {"system": "climate", "command": "set_temperature", "value": "23°C"},
    ],
    "stressed/frustrated": [
        {"system": "ambient", "command": "set_lighting", "value": "warm_dim"},
        {"system": "media", "command": "play_playlist", "value": "calm_acoustic"},
        {"system": "climate", "command": "set_temperature", "value": "22°C"},
    ],
    "happy/positive": [
        {"system": "ambient", "command": "set_lighting", "value": "vibrant"},
        {"system": "media", "command": "play_playlist", "value": "upbeat_drive"},
    ],
    "bored": [
        {"system": "media", "command": "play_playlist", "value": "discover_mix"},
        {"system": "ambient", "command": "set_lighting", "value": "dynamic"},
    ],
}

def get_keyword_actions(text):
    """Detect action-worthy phrases and return extra vehicle actions."""
    text_lower = text.lower()
    extra = []
    if any(w in text_lower for w in ["go home", "want to go home", "take me home", "drive home", "head home"]):
        extra.append({"system": "navigation", "command": "set_destination", "value": "home"})
    if any(w in text_lower for w in ["cold", "freezing", "chilly"]):
        extra.append({"system": "climate", "command": "set_temperature", "value": "25°C"})
    if any(w in text_lower for w in ["hot", "warm", "sweating"]):
        extra.append({"system": "climate", "command": "set_temperature", "value": "20°C"})
    if any(w in text_lower for w in ["close sunroof", "close the sunroof"]):
        extra.append({"system": "sunroof", "command": "close", "value": ""})
    if any(w in text_lower for w in ["open sunroof", "open the sunroof"]):
        extra.append({"system": "sunroof", "command": "open", "value": ""})
    if any(w in text_lower for w in ["play music", "play song", "play something", "put on music"]):
        extra.append({"system": "media", "command": "play_playlist", "value": "liked_songs"})
    return extra

# ── Intent Classification ─────────────────────────────────────────
def classify_intent(text):
    text_lower = text.lower()

    technical_keywords = [
        "how to", "how do", "how long", "how much",
        "what is", "what's", "what are", "where is",
        "charge", "charging", "battery range", "battery", "range",
        "boost mode", "zip mode", "drive mode",
        "tire pressure", "tyre pressure", "psi",
        "warranty", "service", "maintenance",
        "feature", "adas", "safety feature",
        "trunk", "boot", "sunroof how",
        "bluetooth", "connect", "pair",
        "specification", "specs", "horsepower", "torque",
        "dimensions", "weight", "ground clearance",
        "infotainment", "screen", "display how",
        "update", "software",
    ]

    emotional_keywords = [
        "tired", "exhausted", "hectic", "stressed", "frustrated",
        "happy", "great", "amazing", "excited", "good day",
        "sad", "down", "depressed", "upset", "lonely",
        "worried", "anxious", "nervous", "scared",
        "angry", "annoyed", "mad", "furious",
        "bored", "boring",
        "feeling", "i feel", "i'm feeling",
    ]

    has_emotional = any(kw in text_lower for kw in emotional_keywords)
    has_technical = any(kw in text_lower for kw in technical_keywords)

    if has_emotional and has_technical:
        return "mixed"
    if has_emotional:
        return "emotional"
    if has_technical:
        return "technical_query"
    return "conversational"

# ── Emotion Detection ─────────────────────────────────────────────
def detect_emotion_from_text(text):
    text_lower = text.lower()

    if any(w in text_lower for w in ["sad", "down", "depressed", "lonely", "miss", "unhappy", "heartbroken", "cry"]):
        return "sad/down"
    if any(w in text_lower for w in ["tired", "exhausted", "hectic", "drained", "sleepy", "fatigued", "worn out", "long day"]):
        return "stressed/tired"
    if any(w in text_lower for w in ["angry", "annoyed", "furious", "mad", "pissed", "rage"]):
        return "angry/frustrated"
    if any(w in text_lower for w in ["worried", "scared", "anxious", "nervous", "concerned", "panic"]):
        return "anxious/worried"
    if any(w in text_lower for w in ["stressed", "frustrated", "overwhelmed", "pressure"]):
        return "stressed/frustrated"
    if any(w in text_lower for w in ["bored", "dull", "nothing", "whatever", "meh"]):
        return "bored"
    if any(w in text_lower for w in ["happy", "great", "amazing", "excited", "good", "fantastic", "wonderful", "awesome", "love"]):
        return "happy/positive"
    return "neutral/calm"

# ── Execute simulated vehicle actions ──────────────────────────────
def execute_actions(actions):
    if not actions:
        return
    icons = {
        "navigation": "🧭", "climate": "🌡️", "ambient": "💡",
        "media": "🎵", "sunroof": "☀️", "seat": "💺",
        "display": "🖥️", "window": "🪟",
    }
    print("  ┌─── Vehicle Actions ───────────────────────")
    for a in actions:
        icon = icons.get(a["system"], "⚙️")
        print(f"  │ {icon}  {a['system'].upper()}: {a['command']} → {a['value']}")
    print("  └────────────────────────────────────────────")

# ── LLM Calls ─────────────────────────────────────────────────────
def ask_llm_emotional(user_text, emotion, actions_taken):
    """Free-text conversational response — warm and human like v1."""
    action_summary = ""
    if actions_taken:
        parts = []
        for a in actions_taken:
            if a["system"] == "navigation":
                parts.append("set navigation to home")
            elif a["system"] == "media":
                parts.append(f"put on {a['value'].replace('_', ' ')} music")
            elif a["system"] == "climate":
                parts.append(f"set the cabin to {a['value']}")
            elif a["system"] == "ambient":
                parts.append(f"set lighting to {a['value'].replace('_', ' ')}")
            elif a["system"] == "display":
                parts.append("dimmed the display")
            elif a["system"] == "sunroof":
                parts.append(f"{a['command']}d the sunroof")
        if parts:
            action_summary = f"\n\nYou have already done these for the driver: {', '.join(parts)}. Mention what you did casually in 1-2 sentences — don't list them out."
        else:
            action_summary = "\n\nYou have NOT taken any vehicle actions. Do NOT claim you adjusted anything. Just respond naturally to what the driver said."
    else:
        action_summary = "\n\nYou have NOT taken any vehicle actions. Do NOT claim you adjusted anything. Just respond naturally to what the driver said."

    prompt = f'Driver says: "{user_text}"\nDetected emotion: {emotion}{action_summary}'

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "system": EMOTIONAL_PROMPT,
        "stream": False
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
        if resp.status_code == 200:
            return resp.json()["response"].strip()
    except Exception as e:
        print(f"⚠️  LLM error: {e}")
    return "Hey, I'm here. Let me make things a bit easier for you."

def ask_llm_technical(user_text, manual_context):
    """Concise factual answer using manual context."""
    prompt = f'Driver asks: "{user_text}"'
    if manual_context:
        prompt += f"\n\nRelevant BE6 manual info:\n{manual_context}"
    else:
        prompt += "\n\nNo manual section found. Answer from general BE6 knowledge."

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "system": TECHNICAL_PROMPT,
        "stream": False
    }
    try:
        resp = requests.post(OLLAMA_URL, json=payload, timeout=120)
        if resp.status_code == 200:
            return resp.json()["response"].strip()
    except Exception as e:
        print(f"⚠️  LLM error: {e}")
    return "I couldn't find that info right now — try asking again."

# ── Main ───────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("   ARIA — Intelligent Car Infotainment and Control")
    print("   Proactive AI · Voice + Emotion · Mahindra BE6")
    print("   100% Offline — No Internet Required")
    print("=" * 60)

    print("\nLoading systems...")
    print("🎙️  Loading Whisper...")
    whisper_model = whisper.load_model("base")
    print("✅ Whisper ready!")

    collection = load_rag_database()

    print("\n✅ All systems ready!")
    print("\nTry saying:")
    print("  - 'Today was hectic, I just want to go home'")
    print("  - 'How long does it take to charge the BE6?'")
    print("  - 'I'm feeling really tired'")
    print("  - 'What is Boost mode?'")
    print("  - 'I'm sad, play something nice'")
    print("\nPress Ctrl+C to quit\n")

    while True:
        try:
            input("⏎  Press Enter then speak...")
        except KeyboardInterrupt:
            print("\n\n👋 ARIA signing off. Drive safe!")
            break

        print(f"🎙️  Listening for {DURATION} seconds...")
        try:
            audio = sd.rec(int(DURATION * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype='float32')
            sd.wait()
        except KeyboardInterrupt:
            print("\n\n👋 ARIA signing off. Drive safe!")
            break

        print("✅ Got it. Processing...")
        audio_int = (audio * 32767).astype(np.int16)
        wav.write("temp_input.wav", SAMPLE_RATE, audio_int)

        result = whisper_model.transcribe("temp_input.wav")
        user_text = result["text"].strip()

        if not user_text or len(user_text) < 2:
            print("⚠️  Didn't catch that. Try again.\n")
            continue

        print(f'📝 You said: "{user_text}"')

        # Step 1: Emotion
        emotion = detect_emotion_from_text(user_text)
        print(f"😊 Emotion: {emotion}")

        # Step 2: Intent
        intent = classify_intent(user_text)
        print(f"🎯 Intent: {intent}")

        # Step 3: Route
        if intent in ("emotional", "conversational"):
            # ━━━ EMOTIONAL: hardcoded actions + free-text LLM ━━━
            print("📖 Skipping manual (not a technical question)")
            actions = EMOTION_ACTIONS.get(emotion, []).copy()
            actions.extend(get_keyword_actions(user_text))
            seen = {}
            for a in actions:
                seen[a["system"]] = a
            actions = list(seen.values())
            if actions:
                execute_actions(actions)
            print("🧠 Thinking...")
            response = ask_llm_emotional(user_text, emotion, actions)
            speak(response)

        elif intent == "technical_query":
            # ━━━ TECHNICAL: RAG + factual LLM ━━━
            # Still check for action keywords (e.g. "go home" + "battery")
            kw_actions = get_keyword_actions(user_text)
            if kw_actions:
                execute_actions(kw_actions)
            print("🔍 Searching BE6 manual...")
            ctx = search_manual(collection, user_text)
            print("📖 Found manual info" if ctx else "📖 No manual info found")
            print("🧠 Thinking...")
            response = ask_llm_technical(user_text, ctx)
            speak(response)

        elif intent == "mixed":
            # ━━━ MIXED: actions + RAG + both LLM modes ━━━
            actions = EMOTION_ACTIONS.get(emotion, []).copy()
            actions.extend(get_keyword_actions(user_text))
            seen = {}
            for a in actions:
                seen[a["system"]] = a
            actions = list(seen.values())
            if actions:
                execute_actions(actions)
            print("🔍 Searching BE6 manual...")
            ctx = search_manual(collection, user_text)
            print("🧠 Thinking...")
            emo_resp = ask_llm_emotional(user_text, emotion, actions)
            if ctx:
                tech_resp = ask_llm_technical(user_text, ctx)
                speak(f"{emo_resp} {tech_resp}")
            else:
                speak(emo_resp)

if __name__ == "__main__":
    main()