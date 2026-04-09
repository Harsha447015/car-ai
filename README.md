 Intelligent Car Infotainment and Control



 A proactive, multimodal, LLM-based in-vehicle AI assistant that infers 

 emotional state from natural speech and responds intelligently.



 Stack

 Speech to Text: OpenAI Whisper (local)

 LLM: Llama 3 8B via Ollama (local, no internet)

 Text to Speech: pyttsx3



# \## How to Run

# 1\. Start Ollama: `ollama serve`

# 2\. Run: `python car\_ai.py`

# 3\. Press Enter and speak

# 

# \## Status

# Week 1 - Base voice pipeline working

PS C:\car_ai> & c:\python314\python.exe c:/car_ai/.claude/worktrees/practical-ramanujan/aria.py
pygame-ce 2.5.7 (SDL 2.32.10, Python 3.14.3)
==============================================================
   ARIA — Intelligent Car AI  ·  Mahindra BE6
   Your companion, not just your assistant.
   100% Offline  ·  No Internet  ·  Always With You
==============================================================

Initialising ARIA...
🎙️  Loading Whisper...
✅ Whisper ready!
📂 Loading BE6 knowledge base...
✅ BE6 manual ready!

✅ ARIA is ready.

Try saying:
  · 'I had the worst day, I'm completely drained'
  · 'I'm feeling really anxious about something'
  · 'How long does it take to charge the BE6?'
  · 'Play some jazz'
  · 'I'm so angry, everything went wrong'

Ctrl+C to quit

⏎  Press Enter then speak...
🎙️  Listening for 10 seconds...
✅ Got it. Processing...
C:\Users\Harshavardhan\AppData\Roaming\Python\Python314\site-packages\whisper\transcribe.py:132: UserWarning: FP16 is not supported on CPU; using FP32 instead
  warnings.warn("FP16 is not supported on CPU; using FP32 instead")

📝 You said: "I am feeling cold today minus Rani and I have slight fever."
   Emotion: neutral/calm  |  Intent: emotional
   📖 Skipping manual (not a technical question)
   🧠 Thinking...
  ┌─── ARIA is acting ───────────────────────────────────────
  │ 🌡️   CLIMATE       Set Temperature → 25°C
  │ 🎵  MEDIA         Play Playlist → Gentle Classical
  └──────────────────────────────────────────────────────────

🤖 ARIA: Aww, sorry to hear that - I've got just the thing for you! I've cranked up the heat and played something soothing.

⏎  Press Enter then speak...
🎙️  Listening for 10 seconds...
✅ Got it. Processing...

📝 You said: "I am tired it has been a really long day"
   Emotion: tired/exhausted  |  Intent: emotional
   📖 Skipping manual (not a technical question)
   🧠 Thinking...
  ┌─── ARIA is acting ───────────────────────────────────────
  │ 🧭  NAVIGATION    Set Destination → Home
  │ 🌡️   CLIMATE       Set Temperature → 23°C
  │ 💡  AMBIENT       Set Lighting → Warm Amber Dim
  │ 🎵  MEDIA         Play Playlist → Lo Fi Calm
  │ 🖥️   DISPLAY       Set Brightness → 30% brightness
  │ 💺  SEAT          Lumbar Support → On
  └──────────────────────────────────────────────────────────

🤖 ARIA: I'm so sorry you're feeling exhausted - I've made things cozy for you. Let's get you home.

⏎  Press Enter then speak...Traceback (most recent call last):