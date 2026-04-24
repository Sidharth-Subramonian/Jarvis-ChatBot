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
from faster_whisper import WhisperModel
import subprocess
from typing import Optional

from config import (
    SAMPLE_RATE, CHUNK_SIZE, SILENCE_LIMIT, VOLUME_THRESHOLD,
    MAX_WAIT_TIME, MIN_SPEECH_TIME, WAKE_WORD, WAKE_WORD_THRESHOLD,
    STT_MODEL, STT_COMPUTE_TYPE, STT_BEAM_SIZE, STT_LANGUAGE,
    TTS_MODEL, TTS_SAMPLE_RATE, logger
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
        """Initialize audio system, wake word model, and speech-to-text engine."""
        logger.info("Initializing Jarvis's Senses...")
        
        self.temp_file = "command.wav"
        
        # Load Faster-Whisper (Optimized for RPi4)
        self.stt_model: WhisperModel = WhisperModel(
            STT_MODEL, device="cpu", compute_type=STT_COMPUTE_TYPE
        )
        
        # Load openWakeWord
        try:
            self.oww_model = Model(wakeword_models=[WAKE_WORD])
        except TypeError:
            logger.warning("openWakeWord version mismatch, using default model loading")
            self.oww_model = Model()
            
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
                
                if WAKE_WORD in self.oww_model.prediction_buffer:
                    score = self.oww_model.prediction_buffer[WAKE_WORD][-1]
                    
                    if score > WAKE_WORD_THRESHOLD:
                        logger.info(f"Wake word detected: {WAKE_WORD} (Score: {score:.2f})")
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
        Converts audio file to text using Faster-Whisper.
        
        Args:
            file_path: Path to WAV file to transcribe
            
        Returns:
            Transcribed text
        """
        hint_prompt = (
            "Arijit Singh, Bollywood, Hindi songs, Indian music titles, "
            "AR Rahman, Pritam, Kesariya, Choley Jeye Na, Kollywood, Tamil Songs"
        )

        try:
            segments, info = self.stt_model.transcribe(
                file_path, 
                beam_size=STT_BEAM_SIZE,
                initial_prompt=hint_prompt, 
                vad_filter=True,
                language=STT_LANGUAGE
            )
            
            text = " ".join([segment.text for segment in segments])
            result = text.strip()
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
        Convert text to speech and play through speakers.
        Pauses music during playback.
        
        Args:
            text: Text to speak
        """
        if not text:
            return
            
        self.stream.stop_stream()
        
        # Use aplay with explicit headphones device (hw:2,0)
        command = (
            f'echo "{text}" | piper --model {TTS_MODEL} '
            f'--output_raw | aplay -D hw:2,0 -r {TTS_SAMPLE_RATE} -f S16_LE -t raw 2>/dev/null'
        )
        
        try:
            subprocess.run(command, shell=True, stderr=subprocess.DEVNULL, timeout=30)
            logger.debug(f"Spoke: {text[:50]}...")
        except Exception as e:
            logger.error(f"Text-to-speech error: {e}")
        finally:
            time.sleep(1)
            
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
