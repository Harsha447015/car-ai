import sounddevice as sd
import numpy as np
import scipy.io.wavfile as wav
import whisper
import requests
import pyttsx3
import chromadb
from chromadb.utils import embedding_functions

# ── Settings ──────────────────────────────────────────────────────
DURATION = 6
SAMPLE_RATE = 16000
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3:8b"
DB_PATH = r"C:\car_ai\be6_database"

# ── Two separate prompts for two different situations ──────────────

# Used when driver is emotional — no manual, pure empathy + action
EMOTIONAL_PROMPT = """You are an intelligent in-vehicle AI companion in a Mahindra BE6.
You understand how the driver feels and respond like a calm, caring friend in the passenger seat.

When the driver expresses emotion or tiredness:
- Acknowledge their feeling in ONE short sentence
- Suggest ONE specific helpful action (navigate home, play calming music, adjust temperature, take a break)
- Be warm, casual, never robotic

Examples of good responses:
- "Sounds like a rough day — I'm setting navigation to home and putting on something relaxing."
- "You need a break. Want me to find a café nearby where you can rest for a bit?"
- "Got it, heading home. I'll keep the cabin cool and quiet for you."

Keep it to 1-2 sentences maximum. Never lecture. Never give safety warnings."""

# Used only when driver asks a car-specific technical question
TECHNICAL_PROMPT = """You are an intelligent in-vehicle AI assistant for the Mahindra BE6.
Answer the driver's technical question using the manual information provided.
Be direct, accurate, and brief — 1-2 sentences maximum.
Never invent data like live battery %, speed, or temperature — those require car connection.
If the manual doesn't have the answer, say so honestly."""

# ── TTS ────────────────────────────────────────────────────────────
tts = pyttsx3.init()
tts.setProperty('rate', 160)
tts.setProperty('volume', 1.0)

def speak(text):
    print(f"\n🤖 AI: {text}\n")
    tts.say(text)
    tts.runAndWait()

# ── Load RAG ───────────────────────────────────────────────────────
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

# ── Smart decision: is this a technical question or emotional? ─────
def is_technical_question(text):
    text_lower = text.lower()
    
    technical_keywords = [
        "charge", "charging", "battery", "range", "km", "miles",
        "adas", "boost", "sunroof", "tyre", "tire", "pressure",
        "service", "warranty", "feature", "mode", "speed", "motor",
        "climate", "ac", "heat", "seat", "display", "screen",
        "navigation", "map", "bluetooth", "connect", "park",
        "brake", "suspension", "ground clearance", "specification",
        "how do i", "how to", "what is", "tell me about",
        "does the", "can i", "how much", "how long", "how many"
    ]
    
    return any(keyword in text_lower for keyword in technical_keywords)

# ── Detect emotion ─────────────────────────────────────────────────
def detect_emotion(text):
    text_lower = text.lower()
    if any(w in text_lower for w in ["tired", "exhausted", "hectic", "stressed", "awful", "terrible", "rough", "hard day"]):
        return "stressed/tired"
    elif any(w in text_lower for w in ["happy", "great", "amazing", "excited", "good", "fantastic", "wonderful"]):
        return "happy/positive"
    elif any(w in text_lower for w in ["worried", "scared", "anxious", "nervous", "concerned"]):
        return "anxious/worried"
    elif any(w in text_lower for w in ["angry", "annoyed", "frustrated", "upset", "mad"]):
        return "angry/frustrated"
    elif any(w in text_lower for w in ["bored", "dull", "nothing"]):
        return "bored"
    elif any(w in text_lower for w in ["sad", "unhappy", "depressed", "down"]):
        return "sad"
    else:
        return "neutral"

# ── Search manual ──────────────────────────────────────────────────
def search_manual(collection, question):
    results = collection.query(
        query_texts=[question],
        n_results=2
    )
    context = ""
    for i, doc in enumerate(results["documents"][0]):
        page = results["metadatas"][0][i]["page"]
        context += f"[Page {page}]: {doc[:600]}\n"
    return context

# ── Ask LLM ────────────────────────────────────────────────────────
def ask_llm(prompt, system):
    payload = {
        "model": MODEL_NAME,
        "prompt": prompt,
        "system": system,
        "stream": False
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=120)
        if response.status_code == 200:
            return response.json()["response"].strip()
        return "Something went wrong, sorry."
    except Exception as e:
        return f"Error: {str(e)}"

# ── Main ───────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("   Intelligent Car Infotainment and Control")
    print("   Voice + Emotion + BE6 Manual Knowledge")
    print("   100% Offline — No Internet Required")
    print("=" * 60)

    print("\nLoading systems...")
    print("🎙️  Loading Whisper...")
    whisper_model = whisper.load_model("base")
    print("✅ Whisper ready!")

    collection = load_rag_database()

    print("\n✅ All systems ready!")
    print("\nTry saying:")
    print("  - 'Today was hectic, take me home'")
    print("  - 'I'm really tired'")
    print("  - 'How long does the BE6 take to charge?'")
    print("  - 'What is Boost mode?'")
    print("  - 'I'm feeling great today!'")
    print("\nPress Ctrl+C to quit\n")

    while True:
        input("⏎  Press Enter then speak...")

        # Record
        print(f"🎙️  Listening for {DURATION} seconds...")
        audio = sd.rec(
            int(DURATION * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype='float32'
        )
        sd.wait()
        audio_int = (audio * 32767).astype(np.int16)
        wav.write("temp_input.wav", SAMPLE_RATE, audio_int)

        # Transcribe
        result = whisper_model.transcribe("temp_input.wav")
        user_text = result["text"].strip()

        if not user_text or len(user_text) < 2:
            print("⚠️  Didn't catch that. Try again.")
            continue

        print(f"📝 You said: \"{user_text}\"")

        # Decide: emotional or technical?
        if is_technical_question(user_text):
            print("🔧 Technical question detected — searching manual...")
            manual_context = search_manual(collection, user_text)
            prompt = f"""Driver asks: "{user_text}"

Relevant BE6 manual info:
{manual_context}

Answer the question directly and briefly."""
            response = ask_llm(prompt, TECHNICAL_PROMPT)

        else:
            emotion = detect_emotion(user_text)
            print(f"💙 Emotional input detected — emotion: {emotion}")
            prompt = f"""Driver says: "{user_text}"
Their emotional state: {emotion}

Respond warmly and suggest one helpful action."""
            response = ask_llm(prompt, EMOTIONAL_PROMPT)

        speak(response)

if __name__ == "__main__":
    main()