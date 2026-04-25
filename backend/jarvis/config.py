import os
import logging
from google import genai
from openai import OpenAI
from dotenv import load_dotenv

# Global runtime control
JARVIS_ENABLED = True


# ============================================================================
# LOGGING SETUP
# ============================================================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# ENVIRONMENT SETUP
# ============================================================================
load_dotenv()

GENAI_KEY = os.getenv("GENAI_API_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")
HA_URL = os.getenv("HA_URL", "").rstrip('/')
HA_TOKEN = os.getenv("HA_TOKEN")

if not GENAI_KEY or not GROQ_KEY:
    missing = []
    if not GENAI_KEY: missing.append("GENAI_API_KEY")
    if not GROQ_KEY: missing.append("GROQ_API_KEY")
    raise ValueError(f"Sir, the following keys are missing from your .env: {', '.join(missing)}")

if HA_URL and not HA_TOKEN:
    logger.warning("HA_URL configured but HA_TOKEN missing. Home Assistant features will be unavailable.")

# ============================================================================
# MODEL CONFIGURATION
# ============================================================================
MODEL_GEMINI = "gemini-2.0-flash-lite"
MODEL_GROQ = "llama-3.3-70b-versatile"

# ============================================================================
# AUDIO CONFIGURATION
# ============================================================================
SAMPLE_RATE = 16000
CHUNK_SIZE = 1280
AUDIO_FORMAT = "pyaudio.paInt16"
SILENCE_LIMIT = 1.5  # seconds
VOLUME_THRESHOLD = 1200
MAX_WAIT_TIME = 7  # seconds to start speaking
MIN_SPEECH_TIME = 1.2  # minimum seconds of speech

# ============================================================================
# VOICE COMMAND CONFIGURATION
# ============================================================================
WAKE_WORD = "hey_jarvis"
WAKE_WORD_THRESHOLD = 0.85
STT_MODEL = "base"
STT_COMPUTE_TYPE = "int8"
STT_BEAM_SIZE = 3
STT_LANGUAGE = "en"
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TTS_MODEL = os.path.join(_SCRIPT_DIR, "piper", "en_GB-alan-medium.onnx")
TTS_SAMPLE_RATE = 22050

# ============================================================================
# SESSION CONFIGURATION
# ============================================================================
SESSION_TIMEOUT = 10  # seconds
HISTORY_SIZE = 10
NONSENSE_FILTER_MIN_WORDS = 2

# ============================================================================
# TIMEZONE
# ============================================================================
TIMEZONE = "Asia/Kolkata"

# ============================================================================
# HOME ASSISTANT CONFIGURATION
# ============================================================================
ATOMBERG_SPEEDS = {
    "0": 0,
    "1": 16,
    "2": 33,
    "3": 50,
    "4": 66,
    "5": 83,
    "6": 100
}

ENTITY_MAP = {
    "fan": "fan.sidhu_fan",
    "sidhu fan": "fan.sidhu_fan",
    "see the fan": "fan.sidhu_fan",
    "sido fan": "fan.sidhu_fan",
    "light": "light.sidhu_fan_led",
    "led": "light.sidhu_fan_led",
    "sidhu fan led": "light.sidhu_fan_led",
}

# ============================================================================
# AI CLIENT INITIALIZATION
# ============================================================================
try:
    gemini_client = genai.Client(api_key=GENAI_KEY)
    logger.info("Gemini client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Gemini client: {e}")
    raise

try:
    groq_client = OpenAI(
        base_url="https://api.groq.com/openai/v1",
        api_key=GROQ_KEY
    )
    logger.info("Groq client initialized successfully")
except Exception as e:
    logger.error(f"Failed to initialize Groq client: {e}")
    raise
