import asyncio
import os
import sys
import tempfile

sys.stdout.reconfigure(encoding='utf-8')

import edge_tts
import numpy as np

import pygame
import requests
import scipy.io.wavfile as wav
import sounddevice as sd
import whisper

DURATION = 6
SAMPLE_RATE = 16000
OLLAMA_URL = "http://localhost:11434/api/generate"
MODEL_NAME = "llama3:8b"
TTS_VOICE = "en-US-AriaNeural"

SYSTEM_PROMPT = """You are an intelligent in-vehicle AI assistant inside a car.
Understand the driver's emotional state from what they say.
Keep responses short, warm and helpful — maximum 2 sentences.
If the driver sounds stressed or tired, acknowledge it and suggest something comforting.
Do not ask too many questions. Be like a calm, smart co-passenger."""


async def speak(text):
    print(f"\n🤖 AI: {text}\n")
    communicate = edge_tts.Communicate(text, voice=TTS_VOICE)

    with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as f:
        tmp_path = f.name

    await communicate.save(tmp_path)

    pygame.mixer.init()
    pygame.mixer.music.load(tmp_path)
    pygame.mixer.music.play()
    await asyncio.sleep(0.1)  # wait for playback to actually start
    while pygame.mixer.music.get_busy():
        await asyncio.sleep(0.05)
    pygame.mixer.music.unload()
    pygame.mixer.quit()
    try:
        os.unlink(tmp_path)
    except OSError:
        pass


def ask_llm(user_text):
    payload = {
        "model": MODEL_NAME,
        "prompt": f'Driver says: "{user_text}"',
        "system": SYSTEM_PROMPT,
        "stream": False
    }
    try:
        response = requests.post(OLLAMA_URL, json=payload, timeout=120)
        if response.status_code == 200:
            return response.json()["response"].strip()
        else:
            return "Sorry, I could not process that."
    except Exception as e:
        return f"Connection error: {str(e)}"


async def main():
    print("=" * 50)
    print("   Intelligent Car AI — Voice Mode")
    print("   Press Enter to speak. Ctrl+C to quit.")
    print("=" * 50)

    print("\nLoading Whisper model...")
    model = whisper.load_model("base")
    print("✅ Whisper ready!")
    print("✅ Ollama running on localhost")
    print("\nSystem ready. Let's go!\n")

    while True:
        input("⏎  Press Enter then speak...")

        print(f"🎙️  Listening for {DURATION} seconds...")
        audio = sd.rec(
            int(DURATION * SAMPLE_RATE),
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype='float32'
        )
        sd.wait()
        print("✅ Recording done. Transcribing...")

        audio_int = (audio * 32767).astype(np.int16)
        wav.write("temp_input.wav", SAMPLE_RATE, audio_int)

        result = model.transcribe("temp_input.wav")
        user_text = result["text"].strip()

        if not user_text or len(user_text) < 2:
            print("⚠️  Didn't catch that. Try again.")
            continue

        print(f"📝 You said: \"{user_text}\"")
        print("🧠 Thinking...")
        response = ask_llm(user_text)
        await speak(response)


if __name__ == "__main__":
    asyncio.run(main())
