import os
import sys
import ctypes
import pyaudio
import wave
import numpy as np
import openwakeword
import time
from openwakeword.model import Model
from faster_whisper import WhisperModel
import subprocess

# --- SILENCE ALSA WARNINGS ---
ERROR_HANDLER_FUNC = ctypes.CFUNCTYPE(None, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p)
def py_error_handler(filename, line, function, err, fmt):
    pass
c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
try:
    asound = ctypes.cdll.LoadLibrary('libasound.so.2')
    asound.snd_lib_error_set_handler(c_error_handler)
except:
    pass

class VoiceSystem:
    def __init__(self):
        print("Initializing Jarvis's Senses...")
        
        # Load Faster-Whisper (Optimized for RPi4)
        self.stt_model = WhisperModel("tiny.en", device="cpu", compute_type="int8")
        
        # LOAD OPENWAKEWORD (FIXED)
        try:
            # Try specific model list first
            self.oww_model = Model(wakeword_models=["hey_jarvis"])
        except TypeError:
            # Fallback for versions that don't like 'wakeword_models'
            print("Notice: Version mismatch detected, using default model loading...")
            self.oww_model = Model()
            
        self.pa = pyaudio.PyAudio()
        self.stream = self.pa.open(
            format=pyaudio.paInt16, 
            channels=1, 
            rate=16000, 
            input=True, 
            frames_per_buffer=1280
        )
        print("Senses initialized. Jarvis is listening, sir.")

    def listen_for_wake_word(self):
        # 1. Hard reset the stream to kill hardware lingering
        self.stream.stop_stream()
        
        # 2. BLANK the internal window
        # This forces openWakeWord to wait for a BRAND NEW 1.28s of audio
        if hasattr(self.oww_model, 'prediction_buffer'):
            for mdl in self.oww_model.prediction_buffer.keys():
                self.oww_model.prediction_buffer[mdl].clear()
        
        time.sleep(0.5) # The "Deaf" period
        self.stream.start_stream()
        
        while True:
            data = self.stream.read(1280, exception_on_overflow=False)
            audio_data = np.frombuffer(data, dtype=np.int16)
            
            # Predict returns the scores for the current window
            self.oww_model.predict(audio_data)
            
            for mdl in self.oww_model.prediction_buffer.keys():
                if self.oww_model.prediction_buffer[mdl][-1] > 0.85:
                    # SUCCESS: But before we return, we must 'poison' the buffer
                    # so it can't trigger again on the same sound
                    self.oww_model.prediction_buffer[mdl].clear()
                    return True

    def record_command(self, silence_limit=1.5, threshold=800): # Lowered threshold slightly
        temp_file = "command.wav"
        print("Listening...", end="", flush=True)
        frames = []
        silent_chunks = 0
        audio_started = False 
        
        min_chunks = (16000 / 1280) * 1.2 
        max_wait_chunks = (16000 / 1280) * 7 # Give 7s to start talking

        while True:
            try:
                data = self.stream.read(1280, exception_on_overflow=False)
                frames.append(data)
                
                audio_data = np.frombuffer(data, dtype=np.int16)
                volume = np.sqrt(np.mean(audio_data.astype(float)**2))

                if volume > threshold:
                    audio_started = True
                    silent_chunks = 0
                else:
                    if audio_started:
                        silent_chunks += 1

                # Condition 1: Stop after speech + silence
                if audio_started and len(frames) > min_chunks:
                    if silent_chunks > ((16000 / 1280) * silence_limit):
                        print(" Done.")
                        break
                
                # Condition 2: Stop if user never speaks (Timeout)
                if not audio_started and len(frames) > max_wait_chunks:
                    print(" Timeout.")
                    return None 

            except Exception as e:
                print(f"Stream Error: {e}")
                return None

        # --- SAVE THE FILE (Must be outside the while loop) ---
        with wave.open(temp_file, 'wb') as wf:
            wf.setnchannels(1)
            wf.setsampwidth(self.pa.get_sample_size(pyaudio.paInt16))
            wf.setframerate(16000)
            wf.writeframes(b''.join(frames))
            
        return temp_file

    def transcribe(self, file_path):
        """Converts wav file to text using Faster-Whisper."""
        segments, info = self.stt_model.transcribe(file_path, beam_size=5)
        text = " ".join([segment.text for segment in segments])
        return text.strip()

    def speak(self, text):
        """Hard-Mute speech logic."""
        self.stream.stop_stream()
        
        command = f'echo "{text}" | ./piper/piper --model ./piper/en_GB-alan-medium.onnx --output_raw | aplay -r 22050 -f S16_LE -t raw'
        subprocess.run(command, shell=True, stderr=subprocess.DEVNULL)
        
        # INCREASE cooling time to 0.8s - essential for Raspberry Pi speakers
        time.sleep(1) 
        
        # CLEAR AFTER SPEAKING TOO
        for mdl in self.oww_model.prediction_buffer.keys():
            self.oww_model.prediction_buffer[mdl].clear()
            
        self.stream.start_stream()