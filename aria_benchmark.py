"""
aria_benchmark.py — Timed benchmark for the optimised ARIA build.
Imports directly from aria.py in this worktree.
Runs 50 questions, measures latency per question, writes aria_test_results.md.
"""

import json
import os
import re
import sys
import time
from collections import deque
from datetime import datetime

# ── Offline environment flags (must be set before any HF import) ──────────────
os.environ["TRANSFORMERS_OFFLINE"] = "1"
os.environ["HF_DATASETS_OFFLINE"]  = "1"

# ── Import all logic from the optimised aria.py in this worktree ──────────────
sys.path.insert(0, r"C:\car_ai\.claude\worktrees\exciting-shamir")
from aria import (
    load_rag_database,
    search_manual,
    parse_direct_command,
    classify_intent,
    detect_emotion,
    build_prompt,
    ask_llm,
    parse_response,
    history,
    MODEL_NAME,
    SYSTEM_PROMPT,
    SYSTEM_PROMPT_TECHNICAL,
)

sys.stdout.reconfigure(encoding="utf-8")

# ── 50 Questions ──────────────────────────────────────────────────────────────
QUESTIONS = [
    # ── Category 1: Safety & Diagnostics ──────────────────────────────────────
    {"id":  1, "cat":"Safety & Diagnostics",   "note":"",               "q":"My dashboard has a red blinking light."},
    {"id":  2, "cat":"Safety & Diagnostics",   "note":"",               "q":"There is a warning light flashing on the infotainment screen, what is it?"},
    {"id":  3, "cat":"Safety & Diagnostics",   "note":"",               "q":"The light on the charge port is blinking amber."},
    {"id":  4, "cat":"Safety & Diagnostics",   "note":"",               "q":"I'm driving and a red triangle just popped up behind the steering wheel."},
    {"id":  5, "cat":"Safety & Diagnostics",   "note":"",               "q":"My engine light is on."},
    {"id":  6, "cat":"Safety & Diagnostics",   "note":"",               "q":"The ABS lamp stayed on after I started the car."},
    {"id":  7, "cat":"Safety & Diagnostics",   "note":"",               "q":"My hazard lamps just flashed four times while the car was locked."},
    {"id":  8, "cat":"Safety & Diagnostics",   "note":"",               "q":"There's a white blinking light on the wall charger unit."},
    {"id":  9, "cat":"Safety & Diagnostics",   "note":"",               "q":"I've got a yellow warning light on my dashboard."},
    {"id": 10, "cat":"Safety & Diagnostics",   "note":"",               "q":"The car is beeping and there is a red light, what can it possibly be? Have cool door now."},

    # ── Category 2: Technical & RAG ───────────────────────────────────────────
    {"id": 11, "cat":"Technical & RAG",        "note":"",               "q":"How long does it take to charge the 79 kilowatt-hour battery from zero to full at home?"},
    {"id": 12, "cat":"Technical & RAG",        "note":"",               "q":"What is the real-world highway range for the 59 kilowatt-hour variant?"},
    {"id": 13, "cat":"Technical & RAG",        "note":"",               "q":"If I have the long-range battery, how long does a DC fast charge take?"},
    {"id": 14, "cat":"Technical & RAG",        "note":"",               "q":"I'm going on a 600-kilometer trip with the standard range battery, how many times do I need to stop?"},
    {"id": 15, "cat":"Technical & RAG",        "note":"",               "q":"How do I pair my phone to the Bluetooth?"},
    {"id": 16, "cat":"Technical & RAG",        "note":"",               "q":"What does the green pulsing light on the back of the car mean?"},
    {"id": 17, "cat":"Technical & RAG",        "note":"",               "q":"Is it normal for the hazard lights to come on when I open the bonnet?"},
    {"id": 18, "cat":"Technical & RAG",        "note":"",               "q":"What is the ARAI certified range for this car?"},
    {"id": 19, "cat":"Technical & RAG",        "note":"",               "q":"How long do the hazard lights stay on after an airbag deploys?"},
    {"id": 20, "cat":"Technical & RAG",        "note":"",               "q":"My portable charger has a solid red light, what does that mean?"},

    # ── Category 3: Emotional Intelligence ────────────────────────────────────
    {"id": 21, "cat":"Emotional Intelligence", "note":"",               "q":"Today was absolutely hectic, I just want to go to sleep."},
    {"id": 22, "cat":"Emotional Intelligence", "note":"",               "q":"I'm feeling really anxious about this meeting."},
    {"id": 23, "cat":"Emotional Intelligence", "note":"",               "q":"I am so furious right now, everything went wrong at work."},
    {"id": 24, "cat":"Emotional Intelligence", "note":"",               "q":"I'm heartbroken, I just got some terrible news."},
    {"id": 25, "cat":"Emotional Intelligence", "note":"",               "q":"I feel so drained."},
    {"id": 26, "cat":"Emotional Intelligence", "note":"",               "q":"I'm in a fantastic mood today, let's go!"},
    {"id": 27, "cat":"Emotional Intelligence", "note":"",               "q":"I'm completely bored out of my mind."},
    {"id": 28, "cat":"Emotional Intelligence", "note":"",               "q":"I'm feeling a bit lonely on this drive."},
    {"id": 29, "cat":"Emotional Intelligence", "note":"",               "q":"I'm stressed to the max."},
    {"id": 30, "cat":"Emotional Intelligence", "note":"",               "q":"I've had the worst day imaginable."},

    # ── Category 4: Direct Commands ───────────────────────────────────────────
    {"id": 31, "cat":"Direct Commands",        "note":"",               "q":"Take me home."},
    {"id": 32, "cat":"Direct Commands",        "note":"",               "q":"Set the temperature to 21 degrees."},
    {"id": 33, "cat":"Direct Commands",        "note":"",               "q":"Open the sunroof."},
    {"id": 34, "cat":"Direct Commands",        "note":"",               "q":"Play some jazz music."},
    {"id": 35, "cat":"Direct Commands",        "note":"",               "q":"Turn on my lumbar support."},
    {"id": 36, "cat":"Direct Commands",        "note":"",               "q":"Dim the display brightness to 20 percent."},
    {"id": 37, "cat":"Direct Commands",        "note":"",               "q":"Turn the ambient lighting to blue."},
    {"id": 38, "cat":"Direct Commands",        "note":"",               "q":"Navigate to the nearest coffee shop."},
    {"id": 39, "cat":"Direct Commands",        "note":"",               "q":"Set the ventilation to fresh air."},
    {"id": 40, "cat":"Direct Commands",        "note":"",               "q":"Close the windows."},

    # ── Category 5: Mixed Intent & Memory ─────────────────────────────────────
    {"id": 41, "cat":"Mixed Intent & Memory",  "note":"",               "q":"I'm so stressed out, and on top of that, I don't know how to use the fast charger."},
    {"id": 42, "cat":"Mixed Intent & Memory",  "note":"",               "q":"I'm exhausted. Also, how much range do I lose driving on the highway?"},
    {"id": 43, "cat":"Mixed Intent & Memory",  "note":"",               "q":"I'm terrified, there is a red light flashing on my dashboard!"},
    {"id": 44, "cat":"Mixed Intent & Memory",  "note":"",               "q":"I'm feeling great! By the way, what's my usable battery capacity?"},
    {"id": 45, "cat":"Mixed Intent & Memory",  "note":"Follow-up to Q1","q":"It is a red light. What should I do?"},
    {"id": 46, "cat":"Mixed Intent & Memory",  "note":"Follow-up to Q2","q":"I meant the screen behind the steering wheel."},
    {"id": 47, "cat":"Mixed Intent & Memory",  "note":"Follow-up to Q3","q":"What if I just pull the plug out really hard?"},
    {"id": 48, "cat":"Mixed Intent & Memory",  "note":"Follow-up to Q38","q":"Actually, set the temperature to 19 instead."},
    {"id": 49, "cat":"Mixed Intent & Memory",  "note":"",               "q":"Can you explain that last part again?"},
    {"id": 50, "cat":"Mixed Intent & Memory",  "note":"",               "q":"What are the possibilities?"},
]

CAT_ORDER = [
    "Safety & Diagnostics",
    "Technical & RAG",
    "Emotional Intelligence",
    "Direct Commands",
    "Mixed Intent & Memory",
]

# ── Markdown helpers ──────────────────────────────────────────────────────────
def actions_md(actions):
    if not actions:
        return "_(none)_"
    rows = ["| System | Command | Value |","|--------|---------|-------|"]
    for a in actions:
        rows.append(f"| {a.get('system','')} | {a.get('command','')} | {a.get('value','')} |")
    return "\n".join(rows)

def badge(ms):
    if ms < 50:   return f"⚡ {ms:.0f} ms"
    if ms < 1000: return f"✅ {ms:.0f} ms"
    if ms < 5000: return f"🟡 {ms/1000:.2f} s"
    return f"🔴 {ms/1000:.2f} s"

# ── Main benchmark ────────────────────────────────────────────────────────────
def run_benchmark():
    collection = load_rag_database()

    # Warm up model — first call loads it into VRAM
    print("\n🔥 Warming up LLM (keep_alive=-1, q4_K_M)...")
    t_warm = time.perf_counter()
    _r = ask_llm('{"spoken_response":"ready","actions":[],"emotion_detected":"neutral/calm","emotion_acknowledged":false}')
    warmup_ms = (time.perf_counter() - t_warm) * 1000
    print(f"   Warm-up done in {warmup_ms/1000:.1f} s\n")

    timestamp  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    timings    = []   # (qid, path, ms)
    current_cat = None

    lines = [
        "# ARIA Benchmark Results — Optimised Build",
        f"**Generated:** {timestamp}",
        f"**Model:** `{MODEL_NAME}`  |  **num_ctx:** 2048  |  **keep_alive:** -1  |  **TTS:** pyttsx3 (offline)",
        f"**Warm-up time:** {warmup_ms/1000:.1f} s",
        "",
        "| Legend | |",
        "|---|---|",
        "| ⚡ | Fast path — rule-based, < 50 ms |",
        "| ✅ | LLM / safety path — under 5 s target |",
        "| 🟡 | LLM — over 5 s (yellow flag) |",
        "| 🔴 | LLM — very slow (needs attention) |",
        "",
        "> History resets at each category boundary to prevent cross-category contamination.",
        "> The context-carry guard now reads only DRIVER messages (bug fix from prior run).",
        "",
        "---",
        "",
    ]

    for item in QUESTIONS:
        qid  = item["id"]
        cat  = item["cat"]
        note = item["note"]
        q    = item["q"]

        # Category boundary → clear history
        if cat != current_cat:
            history.clear()
            current_cat = cat
            cat_num = CAT_ORDER.index(cat) + 1
            lines.append(f"## Category {cat_num}: {cat}")
            lines.append("")
            print(f"\n{'='*60}")
            print(f"  {cat}")
            print(f"{'='*60}")

        print(f"\n[Q{qid}/50] {q}")
        t0 = time.perf_counter()

        # ── Fast path ──────────────────────────────────────────────────────
        fast = parse_direct_command(q)
        if fast:
            elapsed_ms = (time.perf_counter() - t0) * 1000
            path     = "fast"
            response = fast["spoken_response"]
            actions  = fast["actions"]
            emotion  = "neutral/calm"
            safety_fired = False
            raw_json = None
            print(f"   ⚡ Fast path  {elapsed_ms:.1f} ms")
            history.append({"driver": q, "aria": response, "emotion": emotion})

        else:
            # ── Understand ─────────────────────────────────────────────────
            emotion = detect_emotion(q)
            intent  = classify_intent(q)

            # ── Critical safety check — current message only + one-turn carry ──
            _cur     = q.lower()
            _RED_PAT = re.compile(r'\bred(?:\s+(?:light|warning|blinking|triangle))?\b')
            _DASH_KWS = ["dashboard","instrument cluster","inside the car",
                         "behind the steering","on my dash","on the dash",
                         "instrument panel","driver display","did"]
            red_ok  = bool(_RED_PAT.search(_cur))
            dash_ok = any(p in _cur for p in _DASH_KWS)
            # One-turn carry: if last driver turn confirmed red+dashboard, extend for follow-ups
            if red_ok and not dash_ok and history:
                _last = history[-1].get("driver","").lower()
                if _RED_PAT.search(_last) and any(p in _last for p in _DASH_KWS):
                    dash_ok = True

            if red_ok and dash_ok:
                path = "safety"
                safety_fired = True
                response = (
                    "A red warning light on your dashboard while driving is critical. "
                    "Please reduce speed and pull over when it's safe. "
                    "This could be a general fault indicator, a 12V battery issue, "
                    "an EPB (electronic parking brake) fault, or a powertrain warning. "
                    "Do not restart the vehicle — head to the nearest Mahindra dealer "
                    "or call Roadside Assistance at 1800 266 7070."
                )
                actions  = [
                    {"system":"navigation","command":"set_destination","value":"nearest_mahindra_dealer"},
                    {"system":"ambient",   "command":"set_lighting",   "value":"alert_red_pulse"},
                    {"system":"display",   "command":"set_brightness",  "value":"100"},
                ]
                raw_json = None
                elapsed_ms = (time.perf_counter() - t0) * 1000
                print(f"   🚨 Safety path  {elapsed_ms:.1f} ms")
                history.append({"driver": q, "aria": response, "emotion": emotion})

            else:
                # ── RAG + LLM ─────────────────────────────────────────────
                safety_fired = False
                path = "llm"
                manual_context = ""
                if intent in ("technical_query","mixed"):
                    manual_context = search_manual(collection, q)
                prompt = build_prompt(q, emotion, intent, manual_context)
                use_system = (
                    SYSTEM_PROMPT_TECHNICAL
                    if intent == "technical_query" and emotion == "neutral/calm"
                    else SYSTEM_PROMPT
                )
                raw_json = ask_llm(prompt, system_prompt=use_system)
                parsed   = parse_response(raw_json)
                elapsed_ms = (time.perf_counter() - t0) * 1000

                if parsed and "spoken_response" in parsed:
                    response = parsed["spoken_response"]
                    actions  = parsed.get("actions",[])
                else:
                    response = re.sub(r'[{}\[\]"\\]',' ', raw_json or "No response.").strip()[:250]
                    actions  = []

                print(f"   🧠 LLM  {elapsed_ms/1000:.2f} s   emotion={emotion}  intent={intent}")
                history.append({"driver": q, "aria": response, "emotion": emotion})

        timings.append((qid, path, elapsed_ms))
        print(f"   → {response[:90]}{'…' if len(response)>90 else ''}")

        # ── Write markdown block ───────────────────────────────────────────
        note_str = f"  _(Follow-up: {note})_" if note else ""
        lines.append(f"### Q{qid} — {q}{note_str}")
        lines.append("")
        if path == "fast":
            lines.append(f"**Path:** ⚡ Fast path (rule-based, no LLM)  |  **Time:** {badge(elapsed_ms)}")
        elif path == "safety":
            lines.append(f"**Path:** 🚨 Critical safety override  |  **Time:** {badge(elapsed_ms)}")
        else:
            lines.append(f"**Path:** 🧠 LLM  |  **Time:** {badge(elapsed_ms)}  |  **Emotion:** {emotion}  |  **Intent:** {intent}")
        lines.append("")
        lines.append("**ARIA says:**")
        lines.append(f"> {response}")
        lines.append("")
        lines.append("**Actions:**")
        lines.append(actions_md(actions))
        lines.append("")
        if raw_json:
            lines.append("<details><summary>Raw LLM output</summary>")
            lines.append("")
            lines.append("```")
            lines.append(raw_json[:2000])
            lines.append("```")
            lines.append("")
            lines.append("</details>")
            lines.append("")
        lines.append("---")
        lines.append("")

    # ── Summary stats ─────────────────────────────────────────────────────────
    fast_times   = [ms for _,p,ms in timings if p == "fast"]
    safety_times = [ms for _,p,ms in timings if p == "safety"]
    llm_times    = [ms for _,p,ms in timings if p == "llm"]
    all_times    = [ms for _,_,ms in timings]

    def stats(lst):
        if not lst: return "—"
        avg = sum(lst)/len(lst)
        mx  = max(lst)
        mn  = min(lst)
        over5 = sum(1 for x in lst if x > 5000)
        return f"avg {avg/1000:.2f}s  |  min {mn/1000:.2f}s  |  max {mx/1000:.2f}s  |  >{5}s: {over5}/{len(lst)}"

    summary = [
        "## Summary",
        "",
        f"**Total questions:** 50  |  **Total time:** {sum(all_times)/1000:.1f} s",
        "",
        "| Path | Count | Latency |",
        "|------|-------|---------|",
        f"| ⚡ Fast path (rule-based) | {len(fast_times)} | {stats(fast_times)} |",
        f"| 🚨 Safety path | {len(safety_times)} | {stats(safety_times)} |",
        f"| 🧠 LLM path | {len(llm_times)} | {stats(llm_times)} |",
        "",
        "### Per-question timing",
        "",
        "| Q | Path | Time |",
        "|---|------|------|",
    ]
    for qid, path, ms in timings:
        icon = {"fast":"⚡","safety":"🚨","llm":"🧠"}[path]
        summary.append(f"| Q{qid} | {icon} {path} | {badge(ms)} |")

    lines = summary + ["","---",""] + lines

    out_path = r"C:\car_ai\.claude\worktrees\exciting-shamir\aria_test_results.md"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    # ── Console summary ───────────────────────────────────────────────────────
    print(f"\n{'='*60}")
    print("  BENCHMARK COMPLETE")
    print(f"{'='*60}")
    print(f"  Fast path:    {len(fast_times):2d} questions  (avg {sum(fast_times)/max(len(fast_times),1):.1f} ms)")
    print(f"  Safety path:  {len(safety_times):2d} questions")
    print(f"  LLM path:     {len(llm_times):2d} questions")
    if llm_times:
        over5 = sum(1 for x in llm_times if x > 5000)
        print(f"  LLM avg:      {sum(llm_times)/len(llm_times)/1000:.2f} s   (>{5}s: {over5}/{len(llm_times)})")
    print(f"\n  Results → {out_path}")


if __name__ == "__main__":
    run_benchmark()
