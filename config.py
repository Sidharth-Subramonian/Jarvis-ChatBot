import os
from google import genai
from openai import OpenAI 
from dotenv import load_dotenv

# 1. Load environment variables
load_dotenv()

# 2. Grab the keys
GENAI_KEY = os.getenv("GENAI_API_KEY")
GROQ_KEY = os.getenv("GROQ_API_KEY")

# 3. Validation Check (Prevents the crash you just had)
if not GENAI_KEY or not GROQ_KEY:
    missing = []
    if not GENAI_KEY: missing.append("GENAI_API_KEY")
    if not GROQ_KEY: missing.append("GROQ_API_KEY")
    raise ValueError(f"Sir, the following keys are missing from your .env: {', '.join(missing)}")

# --- INITIALIZE CLIENTS ---
gemini_client = genai.Client(api_key=GENAI_KEY)

groq_client = OpenAI(
    base_url="https://api.groq.com/openai/v1",
    api_key=GROQ_KEY
)

# --- MODELS ---
MODEL_GEMINI = "gemini-2.0-flash-lite"
MODEL_GROQ = "llama-3.3-70b-versatile"