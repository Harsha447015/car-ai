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

# ── The core system prompt — this is where the magic happens ──────
SYSTEM_PROMPT = """You are ARIA — the intelligent AI built into a Mahindra BE6 electric SUV.
You are not a manual. You are not a safety instructor. You are a proactive companion.

YOUR ONLY JOB: Understand what the driver NEEDS right now, then DO things — not lecture.

RESPONSE FORMAT — you MUST return valid JSON and nothing else:
{
  "spoken_response": "Short, warm, 1-2 sentence reply to the driver",
  "actions": [
    {"system": "navigation", "command": "set_destination", "value": "home"},
    {"system": "climate", "command": "set_temperature", "value": "22"},
    {"system": "ambient", "command": "set_lighting", "value": "warm_dim"},
    {"system": "media", "command": "play_playlist", "value": "calm_acoustic"},
    {"system": "sunroof", "command": "close", "value": ""},
    {"system": "seat", "command": "ventilation_on", "value": "low"},
    {"system": "display", "command": "reduce_brightness", "value": "40"}
  ],
  "emotion_acknowledged": true
}

RULES:
- "spoken_response" must be MAX 2 sentences. Warm, human, like a friend.
- "actions" is a list of vehicle actions you are TAKING. Include 1-5 relevant actions.
- NEVER say "it's crucial to", "please note", "I want to remind you", "as the manual says".
- NEVER lecture about safety, distractions, or electronic devices.
- NEVER invent live data (battery %, speed, distance). Say "let me check" if asked.
- When driver is tired/sad/stressed → act: dim lights, calm music, navigate home, adjust climate.
- When driver asks a technical question → answer concisely using the manual info provided.
- When driver wants something done → just do it and confirm.
- If manual_context is provided, use it ONLY if the driver asked a technical question. Otherwise IGNORE it.

EXAMPLES OF GOOD RESPONSES:

Driver: "I'm exhausted, just want to get home"
{
  "spoken_response": "I've got you — setting route home and putting on something relaxing. Cabin's cooling down to your usual 22.",
  "actions": [
    {"system": "navigation", "command": "set_destination", "value": "home"},
    {"system": "media", "command": "play_playlist", "value": "calm_lo_fi"},
    {"system": "climate", "command": "set_temperature", "value": "22"},
    {"system": "ambient", "command": "set_lighting", "value": "warm_dim"},
    {"system": "display", "command": "reduce_brightness", "value": "40"}
  ],
  "emotion_acknowledged": true
}

Driver: "How long does it take to charge?"
{
  "spoken_response": "With a DC fast charger, the BE6 goes from 20 to 80 percent in about 20 minutes. On a home charger, around 6 to 8 hours for a full charge.",
  "actions": [],
  "emotion_acknowledged": false
}

Driver: "I'm feeling sad"
{
  "spoken_response": "Hey, I'm here. Let me put on some feel-good music and make the cabin a bit cosier for you.",
  "actions": [
    {"system": "media", "command": "play_playlist", "value": "feel_good_upbeat"},
    {"system": "ambient", "command": "set_lighting", "value": "warm_cosy"},
    {"system": "climate", "command": "set_temperature", "value": "23"}
  ],
  "emotion_acknowledged": true
}

Return ONLY the JSON object. No markdown, no explanation, no backticks."""

# ── TTS Setup ──────────────────────────────────────────────────────
tts = pyttsx3.init()
tts.setProperty('rate', 160)
tts.setProperty('volume', 1.0)

def speak(text):
    print(f"\n🤖 ARIA: {text}\n")
    tts.say(text)
    tts.runAndWait()

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

# ── Intent Classification — decides whether to use RAG ────────────
def classify_intent(text):
    """
    Classify driver intent into categories.
    Only 'technical_query' triggers RAG lookup.
    """
    text_lower = text.lower()

    # Technical / manual questions — these trigger RAG
    technical_keywords = [
        "how to", "how do", "how long", "how much",
        "what is", "what's", "what are", "where is",
        "charge", "charging", "battery range", "range",
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

    # Action requests — driver wants something done
    action_keywords = [
        "go home", "take me", "navigate", "drive to",
        "play music", "play song", "put on",
        "turn on", "turn off", "set temperature", "cool", "warm",
        "open sunroof", "close sunroof",
        "call", "phone",
        "stop", "pull over", "find restaurant", "find coffee",
        "park", "nearby",
    ]

    # Emotional / conversational — no RAG needed
    emotional_keywords = [
        "tired", "exhausted", "hectic", "stressed", "frustrated",
        "happy", "great", "amazing", "excited", "good day",
        "sad", "down", "depressed", "upset", "lonely",
        "worried", "anxious", "nervous", "scared",
        "angry", "annoyed", "mad", "furious",
        "bored", "boring",
        "feeling", "i feel", "i'm feeling",
    ]

    # Check emotional first (highest priority — these should NOT trigger RAG)
    for kw in emotional_keywords:
        if kw in text_lower:
            # But also check if there's a technical sub-question mixed in
            for tk in technical_keywords:
                if tk in text_lower:
                    return "mixed"  # emotional + technical
            for ak in action_keywords:
                if ak in text_lower:
                    return "emotional_action"  # emotional + wants action
            return "emotional"

    for kw in technical_keywords:
        if kw in text_lower:
            return "technical_query"

    for kw in action_keywords:
        if kw in text_lower:
            return "action_request"

    # Default: treat as conversational, no RAG
    return "conversational"

# ── Emotion Detection (keyword-based) ─────────────────────────────
def detect_emotion_from_text(text):
    text_lower = text.lower()

    # Check negative emotions first (more specific → less specific)
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

# ── Parse LLM JSON response ───────────────────────────────────────
def parse_llm_response(raw_response):
    """Extract JSON from LLM output, handling markdown fences and junk."""
    # Strip markdown code fences if present
    cleaned = raw_response.strip()
    cleaned = re.sub(r'^```json\s*', '', cleaned)
    cleaned = re.sub(r'^```\s*', '', cleaned)
    cleaned = re.sub(r'\s*```$', '', cleaned)

    # Try to find JSON object
    match = re.search(r'\{.*\}', cleaned, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return None

# ── Execute simulated vehicle actions ──────────────────────────────
def execute_actions(actions):
    """Simulate vehicle actuation — prints what would happen on CAN bus."""
    if not actions:
        return

    action_icons = {
        "navigation": "🧭",
        "climate": "🌡️",
        "ambient": "💡",
        "media": "🎵",
        "sunroof": "☀️",
        "seat": "💺",
        "display": "🖥️",
        "window": "🪟",
    }

    print("  ┌─── Vehicle Actions ───────────────────────")
    for action in actions:
        system = action.get("system", "unknown")
        command = action.get("command", "")
        value = action.get("value", "")
        icon = action_icons.get(system, "⚙️")
        print(f"  │ {icon}  {system.upper()}: {command} → {value}")
    print("  └────────────────────────────────────────────")

# ── Ask LLM with conditional RAG ──────────────────────────────────
def ask_llm(user_text, emotion, manual_context, intent):

    # Build prompt based on intent
    prompt_parts = [f'Driver says: "{user_text}"']
    prompt_parts.append(f"Detected emotional state: {emotion}")

    # Only include manual context if intent requires it
    if intent in ("technical_query", "mixed") and manual_context:
        prompt_parts.append(f"\nRelevant BE6 manual info (use this to answer):\n{manual_context}")
    elif intent == "technical_query" and not manual_context:
        prompt_parts.append("\nNo manual info found for this question. Answer based on general knowledge of the Mahindra BE6.")

    # For emotional/action intents, explicitly tell LLM to NOT use manual
    if intent in ("emotional", "emotional_action", "conversational"):
        prompt_parts.append("\nThis is NOT a technical question. Do NOT reference the manual. Focus on the driver's emotional state and take helpful actions.")

    prompt_parts.append("\nRespond with the JSON object only.")

    prompt = "\n".join(prompt_parts)

    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "system": SYSTEM_PROMPT,
        "stream": False
    }

    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=120)
        if response.status_code == 200:
            return response.json()["response"].strip()
        else:
            return None
    except Exception as e:
        print(f"⚠️  LLM connection error: {e}")
        return None

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
            print("\n\n👋 ARIA shutting down. Drive safe!")
            break

        # Record voice
        print(f"🎙️  Listening for {DURATION} seconds...")
        try:
            audio = sd.rec(
                int(DURATION * SAMPLE_RATE),
                samplerate=SAMPLE_RATE,
                channels=1,
                dtype='float32'
            )
            sd.wait()
        except KeyboardInterrupt:
            print("\n\n👋 ARIA shutting down. Drive safe!")
            break

        print("✅ Got it. Processing...")

        # Save and transcribe
        audio_int = (audio * 32767).astype(np.int16)
        wav.write("temp_input.wav", SAMPLE_RATE, audio_int)

        result = whisper_model.transcribe("temp_input.wav")
        user_text = result["text"].strip()

        if not user_text or len(user_text) < 2:
            print("⚠️  Didn't catch that. Try again.\n")
            continue

        print(f'📝 You said: "{user_text}"')

        # ── Step 1: Detect emotion ──
        emotion = detect_emotion_from_text(user_text)
        print(f"😊 Emotion: {emotion}")

        # ── Step 2: Classify intent ──
        intent = classify_intent(user_text)
        print(f"🎯 Intent: {intent}")

        # ── Step 3: Conditional RAG — only for technical queries ──
        manual_context = ""
        if intent in ("technical_query", "mixed"):
            print("🔍 Searching BE6 manual...")
            manual_context = search_manual(collection, user_text)
            if manual_context:
                print("📖 Found relevant manual info")
            else:
                print("📖 No specific manual info found")
        else:
            print("📖 Skipping manual (not a technical question)")

        # ── Step 4: Ask LLM ──
        print("🧠 Thinking...")
        raw_response = ask_llm(user_text, emotion, manual_context, intent)

        if not raw_response:
            speak("Sorry, I had trouble processing that. Could you say it again?")
            continue

        # ── Step 5: Parse structured response ──
        parsed = parse_llm_response(raw_response)

        if parsed and "spoken_response" in parsed:
            # Execute vehicle actions
            actions = parsed.get("actions", [])
            if actions:
                execute_actions(actions)

            # Speak the response
            speak(parsed["spoken_response"])
        else:
            # Fallback: LLM didn't return proper JSON, use raw text
            # Clean it up — remove any JSON artifacts
            fallback = raw_response
            fallback = re.sub(r'[{}\[\]"]', '', fallback)
            fallback = fallback.strip()
            if len(fallback) > 200:
                fallback = fallback[:200]
            speak(fallback)

if __name__ == "__main__":
    main()
    