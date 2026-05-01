import os
import sys
import ctypes
import logging
import pyaudio
import wave
import numpy as np
import openwakeword
import time
from openwakeword.model import Model
import subprocess
import tempfile
from typing import Optional

import config as cfg
from config import (
    SAMPLE_RATE, CHUNK_SIZE, SILENCE_LIMIT, VOLUME_THRESHOLD,
    MAX_WAIT_TIME, MIN_SPEECH_TIME, WAKE_WORD_THRESHOLD,
    groq_client, logger
)

# --- SILENCE ALSA WARNINGS ---
ERROR_HANDLER_FUNC = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p)
def py_error_handler(filename, line, function, err, fmt):
    pass
c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
try:
    asound = ctypes.cdll.LoadLibrary('libasound.so.2')
    asound.snd_lib_error_set_handler(c_error_handler)
except Exception:
    pass

class VoiceSystem:
    """
    Voice interface handling wake word detection, speech recording, 
    transcription, and text-to-speech synthesis.
    """
    
    def __init__(self):
        """Initialize audio system, wake word model, and Groq API client."""
        logger.info("Initializing Jarvis's Senses...")
        
        self.temp_file = "command.wav"
        
        # Load openWakeWord
        try:
            self.oww_model = Model(wakeword_models=[cfg.WAKE_WORD])
        except TypeError:
            try:
                # Newer versions renamed the parameter
                self.oww_model = Model(wakeword_model_paths=[cfg.WAKE_WORD])
            except TypeError:
                logger.warning("openWakeWord: falling back to default model loading")
                self.oww_model = Model()
        
        # Verify wake word is loaded
        if cfg.WAKE_WORD not in self.oww_model.prediction_buffer:
            available = list(self.oww_model.prediction_buffer.keys())
            logger.warning(f"Wake word '{cfg.WAKE_WORD}' not in loaded models. Available: {available}")
            # Try to find a matching model (e.g. "hey jarvis" vs "hey_jarvis")
            for key in available:
                if "jarvis" in key.lower():
                    logger.info(f"Using '{key}' as wake word instead of '{cfg.WAKE_WORD}'")
                    cfg.WAKE_WORD = key
                    break
            
        self.pa = pyaudio.PyAudio()
        self.stream = self.pa.open(
            format=pyaudio.paInt16, 
            channels=1, 
            rate=SAMPLE_RATE, 
            input=True, 
            frames_per_buffer=CHUNK_SIZE
        )
        logger.info("Senses initialized. Jarvis is listening, sir.")

    def listen_for_wake_word(self) -> bool:
        """
        Listens for the configured wake word while purging internal buffers 
        to prevent double-trigger bugs.
        
        Returns:
            True if wake word detected, False otherwise
        """
        self.stream.stop_stream()
        self._purge_pipeline()
        time.sleep(0.5)
        self.stream.start_stream()
        
        while True:
            try:
                data = self.stream.read(CHUNK_SIZE, exception_on_overflow=False)
                audio_data = np.frombuffer(data, dtype=np.int16)
                
                self.oww_model.predict(audio_data)
                
                if cfg.WAKE_WORD in self.oww_model.prediction_buffer:
                    score = self.oww_model.prediction_buffer[cfg.WAKE_WORD][-1]
                    
                    if score > WAKE_WORD_THRESHOLD:
                        logger.info(f"Wake word detected: {cfg.WAKE_WORD} (Score: {score:.2f})")
                        self._purge_pipeline()
                        return True
            except Exception as e:
                logger.error(f"Error in wake word detection: {e}")
                return False
                
    def _purge_pipeline(self) -> None:
        """Clear prediction buffers and preprocessor state to prevent false triggers."""
        for mdl in self.oww_model.prediction_buffer.keys():
            self.oww_model.prediction_buffer[mdl] = [0.0] * len(
                self.oww_model.prediction_buffer[mdl]
            )
        
        if hasattr(self.oww_model, 'preprocessor'):
            if hasattr(self.oww_model.preprocessor, 'feature_buffer'):
                self.oww_model.preprocessor.feature_buffer.fill(0)
            if hasattr(self.oww_model.preprocessor, 'melspectrogram_buffer'):
                self.oww_model.preprocessor.melspectrogram_buffer.fill(0)
            if hasattr(self.oww_model.preprocessor, 'raw_data_buffer'):
                self.oww_model.preprocessor.raw_data_buffer.clear()

    def record_command(self, silence_limit: float = None, threshold: int = None) -> Optional[str]:
        """
        Record user voice command until silence is detected.
        
        Args:
            silence_limit: Seconds of silence to wait before stopping (default from config)
            threshold: Audio volume threshold to detect speech (default from config)
            
        Returns:
            Path to recorded WAV file, or None if timeout/error occurred
        """
        silence_limit = silence_limit or SILENCE_LIMIT
        threshold = threshold or VOLUME_THRESHOLD
        
        logger.info("Recording command...")
        frames = []
        silent_chunks = 0
        audio_started = False
        
        min_chunks = (SAMPLE_RATE / CHUNK_SIZE) * MIN_SPEECH_TIME
        max_wait_chunks = (SAMPLE_RATE / CHUNK_SIZE) * MAX_WAIT_TIME

        try:
            while True:
                data = self.stream.read(CHUNK_SIZE, exception_on_overflow=False)
                frames.append(data)
                
                audio_data = np.frombuffer(data, dtype=np.int16)
                volume = np.sqrt(np.mean(audio_data.astype(float)**2))

                if volume > threshold:
                    audio_started = True
                    silent_chunks = 0
                else:
                    if audio_started:
                        silent_chunks += 1

                # Stop after speech + silence
                if audio_started and len(frames) > min_chunks:
                    if silent_chunks > ((SAMPLE_RATE / CHUNK_SIZE) * silence_limit):
                        logger.info("Recording completed")
                        break
                
                # Timeout if user never speaks
                if not audio_started and len(frames) > max_wait_chunks:
                    logger.warning("Recording timeout - no speech detected")
                    return None

        except Exception as e:
            logger.error(f"Stream error during recording: {e}")
            return None

        # Save WAV file
        try:
            with wave.open(self.temp_file, 'wb') as wf:
                wf.setnchannels(1)
                wf.setsampwidth(self.pa.get_sample_size(pyaudio.paInt16))
                wf.setframerate(SAMPLE_RATE)
                wf.writeframes(b''.join(frames))
            logger.debug(f"Command saved to {self.temp_file}")
            return self.temp_file
        except Exception as e:
            logger.error(f"Failed to save audio file: {e}")
            return None

    def transcribe(self, file_path: str) -> str:
        """
        Converts audio file to text using Groq Whisper API.
        
        Args:
            file_path: Path to WAV file to transcribe
            
        Returns:
            Transcribed text
        """
        try:
            with open(file_path, "rb") as audio_file:
                transcription = groq_client.audio.transcriptions.create(
                    file=(file_path, audio_file.read()),
                    model="whisper-large-v3-turbo",
                    response_format="text",
                    language="en",
                    prompt=(
                        "Arijit Singh, Bollywood, Hindi songs, Indian music titles, "
                        "AR Rahman, Pritam, Kesariya, Choley Jeye Na, Kollywood, Tamil Songs"
                    )
                )
            
            result = transcription.strip() if isinstance(transcription, str) else str(transcription).strip()
            logger.info(f"Transcribed: {result}")
            return result
        except Exception as e:
            logger.error(f"Transcription error: {e}")
            return ""
        finally:
            # Clean up temp file
            self._cleanup_temp_file()

    def speak(self, text: str) -> None:
        """
        Convert text to speech using Groq Orpheus TTS and play through speakers.
        Pauses music during playback.
        
        Args:
            text: Text to speak
        """
        if not text:
            return
            
        self.stream.stop_stream()
        
        tmp_wav = None
        try:
            # Generate speech via Groq Orpheus TTS
            response = groq_client.audio.speech.create(
                model="canopylabs/orpheus-v1-english",
                voice="troy",
                input=text,
                response_format="wav"
            )
            
            # Write to a temp file
            tmp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            response.write_to_file(tmp_wav.name)
            tmp_wav.close()
            
            # Play through speakers using aplay (hw:2,0 = headphone jack)
            play_cmd = f'aplay -D hw:2,0 {tmp_wav.name}'
            result = subprocess.run(
                play_cmd, shell=True, capture_output=True, text=True, timeout=30
            )
            if result.returncode != 0:
                logger.error(f"aplay failed (exit {result.returncode}): {result.stderr.strip()}")
            else:
                logger.debug(f"Spoke: {text[:50]}...")
        except Exception as e:
            logger.error(f"Text-to-speech error: {e}")
        finally:
            # Clean up temp wav
            if tmp_wav and os.path.exists(tmp_wav.name):
                try:
                    os.remove(tmp_wav.name)
                except Exception:
                    pass
            
            time.sleep(0.5)
            
            # Clear buffers after speaking
            for mdl in self.oww_model.prediction_buffer.keys():
                self.oww_model.prediction_buffer[mdl].clear()
                
            self.stream.start_stream()

    def _cleanup_temp_file(self) -> None:
        """Remove temporary audio files to prevent disk bloat."""
        try:
            if os.path.exists(self.temp_file):
                os.remove(self.temp_file)
                logger.debug(f"Cleaned up {self.temp_file}")
        except Exception as e:
            logger.warning(f"Failed to cleanup temp file: {e}")

    def cleanup(self) -> None:
        """Properly shutdown audio resources."""
        logger.info("Shutting down voice system...")
        self._cleanup_temp_file()
        if self.stream:
            self.stream.stop_stream()
            self.stream.close()
        if self.pa:
            self.pa.terminate()
