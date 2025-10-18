from flask import Flask
from flask_cors import CORS
from flask_sock import Sock
import whisper
import tempfile
import os
import threading
import time
import traceback
import wave
import numpy as np
import json
import torch

app = Flask(__name__)
CORS(app)
sock = Sock(app)

# Configuration
CHUNK_DURATION = 3.0  # Increased from 1.5s for better context
OVERLAP_DURATION = 0.3  # Reduced from 0.5s
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2

# VAD Configuration
VAD_THRESHOLD = 0.5  # Speech probability threshold
ENERGY_THRESHOLD = 0.01  # Minimum energy to consider processing
MIN_SPEECH_DURATION = 0.8  # Minimum speech duration in seconds

print("Loading Whisper model (base)...")
model = whisper.load_model("base")  # Upgraded from "tiny"
print("Model loaded!")

print("Loading Silero VAD model...")
vad_model, utils = torch.hub.load(
    repo_or_dir='snakers4/silero-vad',
    model='silero_vad',
    force_reload=False,
    onnx=False
)
(get_speech_timestamps, save_audio, read_audio, VADIterator, collect_chunks) = utils
print("VAD model loaded!")

# Common hallucination phrases to filter
HALLUCINATION_PHRASES = {
    'thank you for watching',
    'thanks for watching',
    'subscribe',
    'like and subscribe',
    'please subscribe',
    'don\'t forget to subscribe',
    'hit the bell',
    'leave a comment',
    'see you next time',
    'bye bye',
    'you',  # Single word hallucinations
    'thank you',
    'thanks',
}

class TranscriptionSession:
    def __init__(self, ws):
        self.ws = ws
        self.audio_buffer = np.array([], dtype=np.int16)
        self.overlap_buffer = np.array([], dtype=np.int16)
        self.is_recording = False
        self.processing_thread = None
        self.lock = threading.Lock()
        self.chunk_counter = 0
        self.last_transcription = ""  # Track for deduplication
        
    def add_audio_data(self, pcm_data):
        """Add raw PCM audio data (Int16 array)"""
        with self.lock:
            audio_array = np.frombuffer(pcm_data, dtype=np.int16)
            self.audio_buffer = np.concatenate([self.audio_buffer, audio_array])
    
    def get_samples_for_duration(self, duration):
        """Calculate number of samples for given duration"""
        return int(SAMPLE_RATE * duration)
    
    def check_energy(self, audio_array):
        """Check if audio has sufficient energy (not silence)"""
        audio_float = audio_array.astype(np.float32) / 32768.0
        energy = np.mean(np.abs(audio_float))
        return energy > ENERGY_THRESHOLD
    
    def detect_speech_vad(self, audio_array):
        """Use Silero VAD to detect speech in audio"""
        try:
            # Convert to float32 in range [-1, 1]
            audio_float = audio_array.astype(np.float32) / 32768.0
            audio_tensor = torch.from_numpy(audio_float)
            
            # Get speech timestamps
            speech_timestamps = get_speech_timestamps(
                audio_tensor,
                vad_model,
                sampling_rate=SAMPLE_RATE,
                threshold=VAD_THRESHOLD,
                min_speech_duration_ms=int(MIN_SPEECH_DURATION * 1000),
                min_silence_duration_ms=300,
            )
            
            # Calculate total speech duration
            if speech_timestamps:
                total_speech_samples = sum(
                    ts['end'] - ts['start'] for ts in speech_timestamps
                )
                speech_ratio = total_speech_samples / len(audio_array)
                return speech_ratio > 0.3  # At least 30% speech
            return False
            
        except Exception as e:
            print(f"VAD error: {e}")
            return True  # Default to processing if VAD fails
    
    def is_hallucination(self, text):
        """Check if transcription is likely a hallucination"""
        text_lower = text.lower().strip()
        
        # Check for common hallucination phrases
        for phrase in HALLUCINATION_PHRASES:
            if phrase in text_lower:
                return True
        
        # Filter very short transcriptions
        word_count = len(text.split())
        if word_count < 2:
            return True
        
        # Filter if too similar to last transcription (duplicate)
        if self.last_transcription and text_lower == self.last_transcription.lower():
            return True
        
        # Filter repetitive patterns
        words = text_lower.split()
        if len(words) >= 4:
            if len(set(words)) / len(words) < 0.5:  # Less than 50% unique words
                return True
        
        return False
    
    def process_audio_loop(self):
        """Background thread that processes audio chunks"""
        chunk_samples = self.get_samples_for_duration(CHUNK_DURATION)
        overlap_samples = self.get_samples_for_duration(OVERLAP_DURATION)
        
        print(f"Processing loop started")
        print(f"Chunk: {CHUNK_DURATION}s ({chunk_samples} samples)")
        print(f"Overlap: {OVERLAP_DURATION}s ({overlap_samples} samples)")
        print(f"VAD threshold: {VAD_THRESHOLD}")
        print(f"Energy threshold: {ENERGY_THRESHOLD}")
        
        while self.is_recording:
            try:
                time.sleep(0.3)
                
                with self.lock:
                    buffer_samples = len(self.audio_buffer)
                
                if buffer_samples >= chunk_samples:
                    with self.lock:
                        if len(self.overlap_buffer) > 0:
                            process_audio = np.concatenate([
                                self.overlap_buffer,
                                self.audio_buffer[:chunk_samples]
                            ])
                        else:
                            process_audio = self.audio_buffer[:chunk_samples]
                        
                        overlap_start = max(0, chunk_samples - overlap_samples)
                        self.overlap_buffer = self.audio_buffer[overlap_start:chunk_samples].copy()
                        self.audio_buffer = self.audio_buffer[chunk_samples:]
                    
                    # Pre-flight checks before transcription
                    if not self.check_energy(process_audio):
                        print("⊘ Skipped: Insufficient energy (silence)")
                        continue
                    
                    if not self.detect_speech_vad(process_audio):
                        print("⊘ Skipped: No speech detected by VAD")
                        continue
                    
                    # Transcribe if passes all checks
                    self.transcribe_audio_array(process_audio)
                    
            except Exception as e:
                print(f"Error in processing loop: {e}")
                traceback.print_exc()
                try:
                    self.ws.send(json.dumps({
                        'type': 'error',
                        'message': f'Processing error: {str(e)}'
                    }))
                except:
                    pass
        
        # Process remaining audio
        with self.lock:
            min_samples = self.get_samples_for_duration(0.8)
            if len(self.audio_buffer) >= min_samples:
                if len(self.overlap_buffer) > 0:
                    final_audio = np.concatenate([self.overlap_buffer, self.audio_buffer])
                else:
                    final_audio = self.audio_buffer.copy()
                self.audio_buffer = np.array([], dtype=np.int16)
                self.overlap_buffer = np.array([], dtype=np.int16)
            else:
                final_audio = None
        
        if final_audio is not None and self.check_energy(final_audio):
            print(f"Processing final chunk: {len(final_audio)} samples")
            self.transcribe_audio_array(final_audio)
        
        print("Processing loop ended")
    
    def transcribe_audio_array(self, audio_array):
        """Transcribe a numpy audio array with improved settings"""
        temp_path = None
        try:
            self.chunk_counter += 1
            duration = len(audio_array) / SAMPLE_RATE
            
            print(f"\n--- Chunk #{self.chunk_counter} ---")
            print(f"Duration: {duration:.2f}s")
            print(f"Samples: {len(audio_array)}")
            
            # Create temp WAV file
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
                temp_path = temp_wav.name
            
            with wave.open(temp_path, 'wb') as wav_file:
                wav_file.setnchannels(CHANNELS)
                wav_file.setsampwidth(SAMPLE_WIDTH)
                wav_file.setframerate(SAMPLE_RATE)
                wav_file.writeframes(audio_array.tobytes())
            
            print("Transcribing...")
            
            # Improved transcription settings
            result = model.transcribe(
                temp_path,
                language='en',  # Set your language explicitly
                fp16=False,
                condition_on_previous_text=True,  # Better continuity
                no_speech_threshold=0.6,  # Filter silence
                logprob_threshold=-1.0,  # Filter low confidence
                compression_ratio_threshold=2.4,  # Filter repetitive text
            )
            
            text = result["text"].strip()
            
            # Post-processing filters
            if not text:
                print("✗ Empty transcription")
                return
            
            if self.is_hallucination(text):
                print(f"✗ Filtered hallucination: '{text}'")
                return
            
            # Check average log probability for confidence
            if 'segments' in result and result['segments']:
                avg_logprob = np.mean([seg.get('avg_logprob', 0) for seg in result['segments']])
                if avg_logprob < -1.0:  # Low confidence
                    print(f"✗ Low confidence: '{text}' (logprob: {avg_logprob:.2f})")
                    return
            
            print(f"✓ Transcription: '{text}'")
            self.last_transcription = text
            
            self.ws.send(json.dumps({
                'type': 'transcription',
                'text': text
            }))
            
        except Exception as e:
            print(f"Transcription error: {e}")
            traceback.print_exc()
            try:
                self.ws.send(json.dumps({
                    'type': 'error',
                    'message': f'Transcription failed: {str(e)}'
                }))
            except:
                pass
        finally:
            if temp_path and os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
    
    def start(self):
        """Start recording session"""
        with self.lock:
            self.is_recording = True
            self.audio_buffer = np.array([], dtype=np.int16)
            self.overlap_buffer = np.array([], dtype=np.int16)
            self.chunk_counter = 0
            self.last_transcription = ""
        
        self.processing_thread = threading.Thread(target=self.process_audio_loop, daemon=True)
        self.processing_thread.start()
        print("\n🎤 Session started - Ready to receive audio")
    
    def stop(self):
        """Stop recording session"""
        self.is_recording = False
        if self.processing_thread:
            self.processing_thread.join(timeout=5)
        print("🛑 Session stopped\n")

@sock.route('/transcribe')
def transcribe_socket(ws):
    print("\n" + "="*60)
    print("📡 New WebSocket Connection")
    print("="*60)
    
    session = TranscriptionSession(ws)
    
    try:
        ws.send(json.dumps({'type': 'status', 'message': 'Connected to transcription server'}))
        
        while True:
            try:
                message = ws.receive(timeout=30)
                
                if message is None:
                    print("Received None message, connection closing")
                    break
                
                if isinstance(message, str):
                    try:
                        data = json.loads(message)
                        
                        if data.get('type') == 'start':
                            print("▶️ Received START signal")
                            session.start()
                            ws.send(json.dumps({'type': 'status', 'message': 'Recording started'}))
                            
                        elif data.get('type') == 'stop':
                            print("⏹️ Received STOP signal")
                            session.stop()
                            ws.send(json.dumps({'type': 'status', 'message': 'Recording stopped'}))
                    except json.JSONDecodeError as e:
                        print(f"JSON decode error: {e}")
                
                elif isinstance(message, bytes):
                    if session.is_recording:
                        session.add_audio_data(message)
                    else:
                        print("⚠️ Received audio but not recording")
            
            except Exception as inner_e:
                print(f"Error in message loop: {inner_e}")
                traceback.print_exc()
                break
    
    except Exception as e:
        print(f"WebSocket error: {e}")
        traceback.print_exc()
    
    finally:
        session.stop()
        print("="*60)
        print("🔌 WebSocket Connection Closed")
        print("="*60 + "\n")

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🎤 Real-Time Transcription Server (Enhanced)")
    print("="*60)
    print(f"Backend:  http://127.0.0.1:5000")
    print(f"Model:    Whisper Base + Silero VAD")
    print(f"Chunk:    {CHUNK_DURATION}s")
    print(f"Overlap:  {OVERLAP_DURATION}s")
    print(f"Sample:   {SAMPLE_RATE}Hz, {SAMPLE_WIDTH*8}-bit")
    print("="*60 + "\n")
    app.run(debug=True, port=5000, host='0.0.0.0')