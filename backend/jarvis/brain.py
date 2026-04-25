import os
import time
import logging
import subprocess
import warnings
from datetime import datetime
from typing import Dict, List, Optional

from google.genai import types
from dotenv import load_dotenv
import pytz

from config import (
    gemini_client, groq_client, MODEL_GEMINI, MODEL_GROQ,
    SESSION_TIMEOUT, HISTORY_SIZE, NONSENSE_FILTER_MIN_WORDS,
    logger, JARVIS_ENABLED
)
from voice import VoiceSystem
from music_bot import play_music, stop_music, cleanup_music
from ha_bridge import control_home_assistant

# Standard RPi Suppressions
os.environ['ORT_LOGGING_LEVEL'] = '3'
warnings.filterwarnings("ignore")
load_dotenv()


def get_current_time_and_date() -> str:
    """
    Get current time and date in IST timezone.
    
    Returns:
        Formatted string with day, date, and time
    """
    tz = pytz.timezone('Asia/Kolkata')
    now = datetime.now(tz)
    return now.strftime("%A, %B %d, %Y, %I:%M %p")


def _pause_music() -> None:
    """Pause music playback via mpv socket."""
    try:
        if os.path.exists("/tmp/mpvsocket"):
            subprocess.run(
                'echo \'{"command": ["set_property", "pause", true]}\' | socat - /tmp/mpvsocket',
                shell=True,
                stderr=subprocess.DEVNULL,
                timeout=2
            )
            logger.debug("Music paused")
    except Exception as e:
        logger.debug(f"Could not pause music: {e}")


def _resume_music() -> None:
    """Resume music playback via mpv socket."""
    try:
        if os.path.exists("/tmp/mpvsocket"):
            subprocess.run(
                'echo \'{"command": ["set_property", "pause", false]}\' | socat - /tmp/mpvsocket',
                shell=True,
                stderr=subprocess.DEVNULL,
                timeout=2
            )
            logger.debug("Music resumed")
    except Exception as e:
        logger.debug(f"Could not resume music: {e}")


def _build_gemini_tools() -> list:
    """
    Build tool definitions for Gemini API.
    
    Returns:
        List of tool definitions
    """
    ha_tool = {
        "name": "control_home_assistant",
        "description": "Controls smart home devices like fans and lights.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "device_type": {"type": "STRING", "enum": ["light", "fan"]},
                "device_name": {"type": "STRING", "description": "Device name"},
                "action": {"type": "STRING", "description": "on, off, speed 1-6, or percentage"}
            },
            "required": ["device_type", "device_name", "action"]
        }
    }

    music_tool = {
        "name": "play_music",
        "description": "Search YouTube and play music",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "query": {"type": "STRING", "description": "Song name or artist"}
            },
            "required": ["query"]
        }
    }

    stop_music_tool = {
        "name": "stop_music",
        "description": "Stop current music playback",
        "parameters": {"type": "OBJECT", "properties": {}}
    }
    
    find_phone_tool = {
        "name": "find_phone",
        "description": "Rings the user's phone to help them find it when they ask where their phone is.",
        "parameters": {"type": "OBJECT", "properties": {}}
    }
    
    return [ha_tool, music_tool, stop_music_tool, find_phone_tool]


def _handle_gemini_tool_call(fn_name: str, fn_args: dict, chat_session) -> tuple[str, bool]:
    """
    Handle Gemini tool function calls.
    
    Args:
        fn_name: Function name to call
        fn_args: Function arguments
        chat_session: Gemini chat session for follow-up messages
        
    Returns:
        Tuple of (response_text, should_continue)
    """
    try:
        if fn_name == "control_home_assistant":
            result = control_home_assistant(**fn_args)
            response = chat_session.send_message(f"[System Tool Result: {result}]")
            return response.text, True
        
        elif fn_name == "play_music":
            result = play_music(**fn_args)
            return result, True
        
        elif fn_name == "stop_music":
            result = stop_music()
            return result, True
            
        elif fn_name == "find_phone":
            try:
                import requests
                resp = requests.post("http://localhost:8000/find-phone", timeout=5)
                if resp.json().get("success"):
                    return "I am ringing your phone now, sir.", True
                else:
                    return "I'm sorry sir, but I couldn't ring your phone. The device may not be registered.", True
            except Exception as e:
                logger.error(f"Error calling find-phone API: {e}")
                return "I encountered an error trying to ring your phone.", True
        
        else:
            logger.warning(f"Unknown tool called: {fn_name}")
            return "Unknown command", False
    
    except Exception as e:
        logger.error(f"Error handling tool {fn_name}: {e}")
        return f"Tool execution failed: {str(e)}", False


def _handle_groq_fallback(history: List[Dict]) -> str:
    """
    Use Groq as fallback when Gemini quota is exhausted.
    
    Args:
        history: Conversation history
        
    Returns:
        Response from Groq
    """
    logger.info("Gemini quota exhausted, switching to Groq fallback")
    
    fresh_time = get_current_time_and_date()
    groq_messages = [
        {
            "role": "system",
            "content": (
                f"You are Jarvis, a concise AI assistant. Current time: {fresh_time}. "
                "For device control, respond with: 'EXECUTE: [type], [device], [action]'. "
                "Example: 'EXECUTE: fan, sidhu fan, on', 'EXECUTE: music, play, song name', or 'EXECUTE: phone, my phone, find'. "
                "For chat, just respond naturally."
            )
        }
    ] + history[-5:]
    
    groq_resp = groq_client.chat.completions.create(
        model=MODEL_GROQ,
        messages=groq_messages
    )
    response_text = groq_resp.choices[0].message.content
    
    # Parse EXECUTE commands
    if "EXECUTE:" in response_text:
        try:
            cmd_part = response_text.split("EXECUTE:")[1].split("\n")[0].strip()
            parts = [p.strip() for p in cmd_part.split(",")]
            
            if len(parts) >= 3:
                if parts[0].lower() == "music":
                    if parts[1].lower() == "play":
                        query = ",".join(parts[2:])  # Handle multi-word queries
                        result = play_music(query)
                        return result
                    elif parts[1].lower() == "stop":
                        return stop_music()
                elif parts[0].lower() == "phone" and parts[2].lower() == "find":
                    import requests
                    requests.post("http://localhost:8000/find-phone", timeout=5)
                    return "I am ringing your phone now, sir."
                else:
                    result = control_home_assistant(parts[0], parts[1], parts[2])
                    return result
        except (IndexError, ValueError) as e:
            logger.warning(f"Could not parse Groq EXECUTE command: {e}")
    
    return response_text


def run_jarvis() -> None:
    """
    Main Jarvis voice assistant loop.
    Handles wake word detection, speech recognition, AI reasoning, and command execution.
    """
    vocal_unit: Optional[VoiceSystem] = None
    
    try:
        # Initialize
        vocal_unit = VoiceSystem()
        logger.info(f"JARVIS ONLINE (Primary: {MODEL_GEMINI})")
        logger.info("Systems synced. Awaiting wake word...")
        
        history: List[Dict] = []
        
        # Build Gemini chat session
        tools = _build_gemini_tools()
        gemini_chat = gemini_client.chats.create(
            model=MODEL_GEMINI,
            config={
                "system_instruction": "You are Jarvis, a concise AI coordinator. Use tools for home control and music.",
                "tools": [types.Tool(function_declarations=tools)]
            }
        )
        
        while True:
            # Check if Jarvis should still be running
            import config
            if not config.JARVIS_ENABLED:
                logger.info("Jarvis received disable signal")
                break
                
            try:
                if vocal_unit.listen_for_wake_word():
                    _pause_music()
                    vocal_unit.speak("Yes, sir?")
                    
                    session_active = True
                    last_interaction_time = time.time()
                    
                    while session_active:
                        # Check for session timeout
                        if time.time() - last_interaction_time > SESSION_TIMEOUT:
                            logger.info("Session timeout, returning to idle")
                            _resume_music()
                            session_active = False
                            continue
                        
                        # Record and transcribe
                        audio_path = vocal_unit.record_command()
                        
                        if not audio_path:
                            continue
                        
                        user_input = vocal_unit.transcribe(audio_path)
                        
                        # Filter out very short inputs
                        if not user_input or len(user_input.split()) < NONSENSE_FILTER_MIN_WORDS:
                            logger.debug("Filtered out short input")
                            continue
                        
                        logger.info(f"User: {user_input}")
                        history.append({"role": "user", "content": user_input})
                        last_interaction_time = time.time()
                        
                        jarvis_msg = ""
                        
                        try:
                            # PRIMARY BRAIN: GEMINI
                            current_time = get_current_time_and_date()
                            prompt_with_context = f"[Context - Time: {current_time}]\nUser: {user_input}"
                            
                            response = gemini_chat.send_message(prompt_with_context)
                            
                            # Check for tool calls
                            if (response.candidates and 
                                response.candidates[0].content and 
                                response.candidates[0].content.parts and
                                response.candidates[0].content.parts[0].function_call):
                                
                                fn = response.candidates[0].content.parts[0].function_call
                                jarvis_msg, should_continue = _handle_gemini_tool_call(
                                    fn.name, fn.args, gemini_chat
                                )
                            else:
                                jarvis_msg = response.text if response else ""
                        
                        except Exception as e:
                            error_str = str(e)
                            
                            # Check if it's a quota error
                            if "429" in error_str or "ResourceExhausted" in error_str:
                                jarvis_msg = _handle_groq_fallback(history)
                            else:
                                logger.error(f"Gemini error: {e}")
                                jarvis_msg = "I'm having trouble connecting to my primary brain, sir."
                        
                        # Output response
                        if jarvis_msg:
                            logger.info(f"Jarvis: {jarvis_msg}")
                            vocal_unit.speak(jarvis_msg)
                            history.append({"role": "assistant", "content": jarvis_msg})
                            
                            # Stay awake if response is a question
                            if jarvis_msg.strip().endswith("?"):
                                logger.info("Staying awake for follow-up...")
                                last_interaction_time = time.time()
                        
                        # Keep history size manageable
                        if len(history) > HISTORY_SIZE:
                            history = history[-HISTORY_SIZE:]
            
            except KeyboardInterrupt:
                logger.info("Keyboard interrupt received")
                break
            except Exception as e:
                logger.error(f"Session error: {e}", exc_info=True)
                time.sleep(2)
    
    except KeyboardInterrupt:
        logger.info("Shutting down...")
    except Exception as e:
        logger.critical(f"Critical error: {e}", exc_info=True)
    finally:
        if vocal_unit:
            try:
                vocal_unit.speak("Shutting down, sir. Goodbye.")
            except Exception as e:
                logger.warning(f"Could not speak goodbye: {e}")
            
            vocal_unit.cleanup()
        
        cleanup_music()
        logger.info("Jarvis offline")


if __name__ == "__main__":
    run_jarvis()
