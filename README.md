# ARIA — Intelligent Car Infotainment and Control

> A proactive, emotion-aware, fully offline AI companion for the **Mahindra BE6** electric SUV.
> Built as a B.Tech research project at Mahindra University, Hyderabad.

---

## What It Does

ARIA listens to the driver, understands how they feel — not just what they say — and acts on it. When you say *"I'm exhausted"*, ARIA doesn't just respond. It closes the sunroof, warms the cabin to 23°C, dims the ambient lighting, queues lo-fi music, and routes you home. All at once, without being asked for each thing.

- **Speech → Whisper** — local transcription, no cloud
- **Emotion detection** — keyword + context analysis across 8 emotional states
- **LLM reasoning** — Llama 3 8B via Ollama, returns structured JSON actions
- **Vehicle actuation** — simulated via virtual CAN bus (vcan0)
- **Natural TTS** — Microsoft neural voice (`en-US-AriaNeural`) via edge-tts
- **BE6 manual RAG** — ChromaDB vector store answers technical questions from the actual vehicle manual
- **Conversation memory** — last 4 turns kept in context so ARIA remembers mid-drive

Everything runs **100% offline**. No internet. No external API calls.

---

## Project Structure

| File | Description |
|------|-------------|
| `car_ai.py` | Original voice assistant (Whisper → Ollama → pyttsx3 TTS) |
| `claude_codes_work.py` | Edge-tts upgrade of car_ai.py — same pipeline, natural neural voice |
| `aria.py` | Full ARIA assistant — emotion profiles, RAG, actions, memory, async |
| `be6_rag.py` | Script that ingests the BE6 vehicle manual into ChromaDB |
| `be6_database/` | ChromaDB vector store of the BE6 manual |
| `Vehicle Manual_BE6_compressed.pdf` | Source manual for RAG |

---

## Architecture

```
Microphone
    │
    ▼
Whisper (local ASR)
    │
    ▼
Emotion Detection ──────────────────┐
    │                               │
Intent Classification               │
    │                               │
    ├── Technical? → ChromaDB RAG   │
    │                               │
    ▼                               ▼
Llama 3 8B via Ollama  ←  Conversation History (4 turns)
    │
    ▼
Structured JSON Response
    ├── spoken_response → edge-tts → Cabin speakers
    └── actions[]       → Virtual CAN bus (vcan0)
```

---

## Emotion → Action Profiles

| Emotion | Key Actions |
|---------|-------------|
| Tired / Exhausted | Navigate home · 23°C · Warm amber dim · Lo-fi · Sunroof close · Lumbar on · Display 30% |
| Stressed / Overwhelmed | Navigate home · 21°C · Fresh air · Soft blue · Nature sounds · Seat vent |
| Sad / Down | 23°C · Warm cosy lighting · Feel-good gentle · Sunroof partial |
| Angry / Furious | 20°C · Max fresh air · Cool calm lighting · Calming instrumental |
| Anxious / Nervous | 22°C · Fresh air · Soft warm white · Gentle classical |
| Happy / Excited | Vibrant lighting · Upbeat music · Sunroof open · 22°C |

---

## Setup

### Requirements

```bash
pip install openai-whisper sounddevice scipy numpy requests
pip install edge-tts pygame-ce          # neural TTS + audio playback
pip install chromadb                    # BE6 manual RAG
pip install python-obd                  # OBD-II live vehicle data (BE6)
```

> **Note:** Use `pygame-ce` instead of `pygame` on Python 3.14+ — it ships pre-built wheels.

### Run Ollama

```bash
ollama serve
ollama pull llama3:8b
```

### Run ARIA

```bash
python aria.py
```

Press **Enter**, speak, ARIA responds.

---

## Hardware Setup (Mahindra BE6)

| Resource | How We Access It |
|----------|-----------------|
| Cabin microphone | USB directional mic placed in cabin |
| Speaker system | Bluetooth / AUX from laptop |
| Camera | USB webcam on dashboard mount |
| OBD-II / CAN bus | ELM327 USB dongle + `python-obd` (read-only) |
| Compute | ASUS ROG Strix G18 · RTX 5050 · 48GB RAM |

The BE6's MAIA/Snapdragon stack is not touched. We interact only through the standard OBD-II port and peripheral hardware.

---

## Status

| Week | Milestone |
|------|-----------|
| Week 1 | Base voice pipeline · Whisper + Ollama + TTS · Working |
| Week 1 | Edge-tts neural voice · Emotion detection · RAG integration · Done |
| Week 1 | ARIA v1 — full emotion-aware action system · Done |
| Week 2 | DeepFace visual emotion · LoRA fine-tuning · CAN bus integration |

---

*Prepared for Venkat Sir · B.Tech Mechatronics & Robotics · Mahindra University, Hyderabad*
