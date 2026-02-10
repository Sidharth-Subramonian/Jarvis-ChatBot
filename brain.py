from google.genai import types
from dotenv import load_dotenv
from datetime import datetime
from voice import VoiceSystem  # Import your voice module
import pytz
import warnings
import os
import time

from config import gemini_client, groq_client, MODEL_GEMINI, MODEL_GROQ
from ha_bridge import control_home_assistant

# Standard RPi Suppressions
os.environ['ORT_LOGGING_LEVEL'] = '3'
warnings.filterwarnings("ignore")
load_dotenv()

def get_current_time_and_date():
    tz = pytz.timezone('Asia/Kolkata')
    now = datetime.now(tz)
    return now.strftime("%A, %B %d, %Y, %I:%M %p")

def run_jarvis():
    # 1. Initialize Senses and Brain
    vocal_unit = VoiceSystem()
    print(f"--- JARVIS ONLINE (Primary: {MODEL_GEMINI}) ---")
    print("Systems synced. Awaiting wake word...")
    
    history = []

    ha_tool = {
        "name": "control_home_assistant",
        "description": "Controls the Sidhu Fan (fan) and Sidhu Fan LED (light).",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "device_type": {"type": "STRING", "enum": ["light", "fan"]},
                "device_name": {"type": "STRING", "description": "Device name like 'sidhu fan' or 'sidhu fan led'."},
                "action": {"type": "STRING", "description": "on, off, speed 1-6, or percentage 10-100."}
            },
            "required": ["device_type", "device_name", "action"]
        }
    }

    gemini_chat = gemini_client.chats.create(
        model=MODEL_GEMINI,
        config={
            "system_instruction": "You are Jarvis, a concise AI butler. Use tools for hardware control.",
            "tools": [types.Tool(function_declarations=[ha_tool])]
        }
    )

    while True:
        try:
            if vocal_unit.listen_for_wake_word():
                vocal_unit.speak("Yes, sir?")
                
                session_active = True
                last_interaction_time = time.time()

                while session_active:
                    # 1. TIMEOUT CHECK
                    if time.time() - last_interaction_time > 10:
                        print("Session timed out. Going back to idle...")
                        session_active = False
                        continue

                    # 2. CAPTURE
                    audio_path = vocal_unit.record_command()
                    
                    # Safety: Ensure recording actually happened
                    if not audio_path or not os.path.exists(audio_path):
                        continue

                    user_input = vocal_unit.transcribe(audio_path)

                    # 3. NONSENSE FILTER
                    if not user_input or len(user_input.split()) < 2:
                        continue

                    print(f"\nUser (Voice): {user_input}")
                    history.append({"role": "user", "content": user_input})
                    last_interaction_time = time.time() 

                    jarvis_msg = "" # Initialize to prevent UnboundLocalError

                    try:
                        # --- PRIMARY BRAIN: GEMINI ---
                        current_time = get_current_time_and_date()
                        prompt_with_context = f"[Context - Time: {current_time}]\nUser: {user_input}"
                        
                        response = gemini_chat.send_message(prompt_with_context)
                        
                        if response.candidates[0].content.parts[0].function_call:
                            fn = response.candidates[0].content.parts[0].function_call
                            result = control_home_assistant(**fn.args)
                            response = gemini_chat.send_message(f"[System Tool Result: {result}]")
                        
                        jarvis_msg = response.text

                    except Exception as e:
                        # --- FALLBACK BRAIN: GROQ ---
                        if "429" in str(e) or "ResourceExhausted" in str(e):
                            print(f"\n[!] Gemini Quota Exhausted. Switching to Groq...")
                            fresh_time = get_current_time_and_date()
                            groq_messages = [
                            {
                                "role": "system", 
                                "content": (
                                    f"You are Jarvis, a loyal and efficient AI butler. Be Concise unless asked to elaborate. Current Time: {fresh_time}. "
                                    "1. If the user is just saying 'Hi', 'Hello', or chatting, respond politely but do NOT execute any commands. "
                                    "2. ONLY if the user specifically asks to turn something on/off or set a speed, use the format: 'EXECUTE: [type], [name], [action]'. "
                                    "3. Devices you control: 'sidhu fan' and 'sidhu fan led'. "
                                    "4. For hardware: 'EXECUTE: fan, sidhu fan, [on/off/1-6]' or 'EXECUTE: light, sidhu fan led, [on/off]'."
                                )
                            }
                            ] + history[-5:]
                            
                            groq_resp = groq_client.chat.completions.create(model=MODEL_GROQ, messages=groq_messages)
                            jarvis_msg = groq_resp.choices[0].message.content
                            
                            if "EXECUTE:" in jarvis_msg:
                                parts = jarvis_msg.replace("EXECUTE:", "").strip().split(",")
                                if len(parts) >= 3:
                                    res = control_home_assistant(parts[0].strip(), parts[1].strip(), parts[2].strip())
                                    jarvis_msg = res # Use hardware result as the spoken response
                        else:
                            print(f"Gemini Error: {e}")
                            jarvis_msg = "I'm having trouble connecting to my primary brain, sir."

                    # 4. FINAL OUTPUT (Unified for both Gemini and Groq)
                    if jarvis_msg:
                        print(f"Jarvis: {jarvis_msg}")
                        vocal_unit.speak(jarvis_msg)
                        history.append({"role": "assistant", "content": jarvis_msg})
                        
                        # Handle the Question Mark Stay-Awake logic
                        if jarvis_msg.strip().endswith("?"):
                            print("Staying awake for follow-up...")
                            last_interaction_time = time.time()
                        
                    if len(history) > 10: history = history[-10:]

        except KeyboardInterrupt:
            vocal_unit.speak("Shutting down, sir. Goodbye.")
            break
        except Exception as e:
            print(f"\nCritical Error: {e}")
            time.sleep(2) # Prevent rapid crash-loop

if __name__ == "__main__":
    run_jarvis()