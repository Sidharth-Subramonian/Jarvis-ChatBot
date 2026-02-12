# 🤖 Jarvis Voice Assistant

**Jarvis** is a privacy-focused, high-performance Edge AI assistant built for the **Raspberry Pi 4**. It bridges the gap between local "Senses" and cloud-based "Intelligence" to provide a seamless, hands-free experience for smart home control, information retrieval, and multimedia orchestration.


---

## ✨ Features

- **Local Senses:** Low-latency wake word detection via `openWakeWord` and optimized Speech-to-Text using `Faster-Whisper` (int8 quantization).
- **Hybrid Intelligence:** - **Primary:** Google Gemini 2.0 Flash for complex reasoning and native tool use.
  - **Fallback:** Groq (Llama-3) for near-instant responses during quota limits.
- **Smart Home Integration:** Native bridge to **Home Assistant** for controlling fans (Atomberg/PWM), lighting, and LEDs.
- **Continuous Conversation:** Multi-turn dialogue support with a 10-second active session window and question-detection to stay awake.
- **Multimedia Engine:** YouTube music streaming directly on the Pi via `yt-dlp` and `mpv`.
- **Barge-in Support:** Non-blocking speech allows you to interrupt Jarvis while he is talking.

---

## 🛠️ Technical Stack

| Component | Technology |
| :--- | :--- |
| **Hardware** | Raspberry Pi 4 (8GB) |
| **Wake Word** | openWakeWord (Hey Jarvis) |
| **STT** | Faster-Whisper (tiny.en) |
| **TTS** | Piper (Alan-medium) |
| **Logic** | Python 3.9+ |
| **AI APIs** | Google Gemini & Groq |
| **Automation** | Home Assistant REST API |

---

## 📂 Project Structure

- `brain.py`: The central loop managing state, session timing, and AI logic.
- `voice.py`: Audio interface for recording, transcribing, and non-blocking speech.
- `ha_bridge.py`: Hardware mapping and Home Assistant communication.
- `music_bot.py`: Background thread handler for YouTube audio streaming.
- `config.py`: Environment configuration and API client initialization.

---

## 🚀 Installation & Setup

### 1. Hardware Requirements
- Raspberry Pi 4
- USB Microphone
- 3.5mm or USB Speakers

### 2. Software Dependencies
```bash
# System dependencies
sudo apt update
sudo apt install mpv aplay -y

# Python environment
pip install -r requirements.txt

```

### 3. Configuration

Create a `.env` file in the root directory:

```env
GEMINI_API_KEY=your_gemini_key
GROQ_API_KEY=your_groq_key
HA_URL=http://your-ha-ip:8123/api
HA_TOKEN=your_long_lived_access_token

```

### 4. Running the Assistant

```bash
# Run with ALSA suppression for a clean terminal
python brain.py 2>/dev/null

```

---

## 📝 Future Roadmap

* [ ] Integration with n8n for personalized WhatsApp/Email notifications.
* [ ] Adaptive volume control based on ambient room noise.
* [ ] Local vision capabilities using a Pi Camera.

---

## ⚖️ License

Distributed under the MIT License.
