import os
import requests
import re
from dotenv import load_dotenv

load_dotenv()

HA_URL = os.getenv("HA_URL").rstrip('/')
HA_TOKEN = os.getenv("HA_TOKEN")

# Precision map for Atomberg speed steps (16% increments)
ATOMBERG_SPEEDS = {
    "0": 0,
    "1": 16,
    "2": 33,
    "3": 50,
    "4": 66,
    "5": 83,
    "6": 100
}

# Master Mapping for your specific hardware
ENTITY_MAP = {
    "fan": "fan.sidhu_fan",
    "sidhu fan": "fan.sidhu_fan",
    "see the fan": "fan.sidhu_fan", # Common phonetic misstep
    "sido fan": "fan.sidhu_fan",    # Another phonetic variation
    "light": "light.sidhu_fan_led",
    "led": "light.sidhu_fan_led",
    "sidhu fan led": "light.sidhu_fan_led",
}

def control_home_assistant(device_type, device_name, action):
    """
    Modular bridge for Home Assistant with priority-based logic.
    Handles Fans (Speeds/On/Off) and Lights (LEDs).
    """
    name_clean = device_name.lower().strip()
    action_clean = action.lower().strip()
    
    # 1. SMART ENTITY MAPPING (Forces LED domain if 'light' or 'led' is mentioned)
    if any(x in name_clean for x in ["led", "light"]):
        entity_id = "light.sidhu_fan_led"
        domain = "light"
    elif "sidhu" in name_clean:
        entity_id = "fan.sidhu_fan"
        domain = "fan"
    else:
        # Fallback for future devices (Hue, etc.)
        domain = device_type.lower() if device_type else "homeassistant"
        entity_id = f"{domain}.{name_clean.replace(' ', '_')}"

    # 2. EXTRACT DIGITS (For speed/percentage control)
    digits = re.findall(r'\d+', action_clean)
    
    # --- COMMAND PRIORITY LOGIC ---
    
    # PRIORITY 1: ABSOLUTE OFF
    # If "off" is in the command, or level is 0, force turn_off service.
    if "off" in action_clean or (digits and digits[0] == "0"):
        endpoint = f"{HA_URL}/services/{domain}/turn_off"
        payload = {"entity_id": entity_id}
        msg = f"Done, sir. The {device_name} is now OFF."
        
    # PRIORITY 2: SPEED CONTROL (Only for fans)
    # If a number (1-6) is found and it's a fan, set percentage.
    elif digits and domain == "fan":
        val = str(digits[0])
        # Use Atomberg map if 1-6, otherwise use direct percentage
        percentage = ATOMBERG_SPEEDS.get(val, int(val))
        percentage = min(max(percentage, 0), 100)
        
        endpoint = f"{HA_URL}/services/fan/set_percentage"
        payload = {"entity_id": entity_id, "percentage": percentage}
        msg = f"Done, sir. {device_name} set to level {val} ({percentage}%)."
        
    # PRIORITY 3: STANDARD ON
    else:
        endpoint = f"{HA_URL}/services/{domain}/turn_on"
        payload = {"entity_id": entity_id}
        msg = f"Done, sir. The {device_name} is now ON."

    # 3. EXECUTION
    headers = {
        "Authorization": f"Bearer {HA_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        print(f"DEBUG: Endpoint: {endpoint} | Payload: {payload}")
        response = requests.post(endpoint, headers=headers, json=payload, timeout=5)
        
        if response.status_code in [200, 201]:
            return msg
        else:
            return f"System Error: {response.status_code} - {response.text}"
            
    except Exception as e:
        return f"Connection Failed: {e}"