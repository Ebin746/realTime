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
import json  # ADD THIS IMPORT

app = Flask(__name__)
CORS(app)
sock = Sock(app)

# Configuration
CHUNK_DURATION = 1.5  # Process every 1.5 seconds
OVERLAP_DURATION = 0.5  # Keep 0.5s overlap for continuity
SAMPLE_RATE = 16000
CHANNELS = 1
SAMPLE_WIDTH = 2  # 16-bit

print("Loading Whisper model...")
model = whisper.load_model("tiny")
print("Model loaded!")

class TranscriptionSession:
    def __init__(self, ws):
        self.ws = ws
        self.audio_buffer = np.array([], dtype=np.int16)  # Raw PCM buffer
        self.overlap_buffer = np.array([], dtype=np.int16)  # Overlap buffer
        self.is_recording = False
        self.processing_thread = None
        self.lock = threading.Lock()
        self.chunk_counter = 0
        
    def add_audio_data(self, pcm_data):
        """Add raw PCM audio data (Int16 array)"""
        with self.lock:
            audio_array = np.frombuffer(pcm_data, dtype=np.int16)
            self.audio_buffer = np.concatenate([self.audio_buffer, audio_array])
    
    def get_samples_for_duration(self, duration):
        """Calculate number of samples for given duration"""
        return int(SAMPLE_RATE * duration)
    
    def process_audio_loop(self):
        """Background thread that processes audio chunks"""
        chunk_samples = self.get_samples_for_duration(CHUNK_DURATION)
        overlap_samples = self.get_samples_for_duration(OVERLAP_DURATION)
        
        print(f"Processing loop started")
        print(f"Chunk: {CHUNK_DURATION}s ({chunk_samples} samples)")
        print(f"Overlap: {OVERLAP_DURATION}s ({overlap_samples} samples)")
        
        while self.is_recording:
            try:
                time.sleep(0.3)  # Check every 300ms
                
                # Check buffer size
                with self.lock:
                    buffer_samples = len(self.audio_buffer)
                
                # Process if we have enough data
                if buffer_samples >= chunk_samples:
                    with self.lock:
                        # Get audio to process (overlap + new chunk)
                        if len(self.overlap_buffer) > 0:
                            process_audio = np.concatenate([
                                self.overlap_buffer,
                                self.audio_buffer[:chunk_samples]
                            ])
                        else:
                            process_audio = self.audio_buffer[:chunk_samples]
                        
                        # Save overlap for next iteration
                        overlap_start = max(0, chunk_samples - overlap_samples)
                        self.overlap_buffer = self.audio_buffer[overlap_start:chunk_samples].copy()
                        
                        # Remove processed samples
                        self.audio_buffer = self.audio_buffer[chunk_samples:]
                    
                    # Transcribe outside the lock
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
        
        # Process remaining audio when recording stops
        with self.lock:
            min_samples = self.get_samples_for_duration(0.5)
            if len(self.audio_buffer) >= min_samples:
                if len(self.overlap_buffer) > 0:
                    final_audio = np.concatenate([self.overlap_buffer, self.audio_buffer])
                else:
                    final_audio = self.audio_buffer.copy()
                self.audio_buffer = np.array([], dtype=np.int16)
                self.overlap_buffer = np.array([], dtype=np.int16)
            else:
                final_audio = None
        
        if final_audio is not None:
            print(f"Processing final chunk: {len(final_audio)} samples")
            self.transcribe_audio_array(final_audio)
        
        print("Processing loop ended")
    
    def transcribe_audio_array(self, audio_array):
        """Transcribe a numpy audio array (int16)"""
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
            
            # Save as WAV
            with wave.open(temp_path, 'wb') as wav_file:
                wav_file.setnchannels(CHANNELS)
                wav_file.setsampwidth(SAMPLE_WIDTH)
                wav_file.setframerate(SAMPLE_RATE)
                wav_file.writeframes(audio_array.tobytes())
            
            print("Transcribing...")
            
            # Transcribe
            result = model.transcribe(temp_path, language=None, fp16=False)
            text = result["text"].strip()
            
            if text:
                print(f"✓ Transcription: '{text}'")
                # IMPORTANT: Send as JSON string
                self.ws.send(json.dumps({
                    'type': 'transcription',
                    'text': text
                }))
            else:
                print("✗ No speech detected")
            
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
        # Send connection confirmation as JSON
        ws.send(json.dumps({'type': 'status', 'message': 'Connected to transcription server'}))
        
        while True:
            try:
                message = ws.receive(timeout=30)
                
                if message is None:
                    print("Received None message, connection closing")
                    break
                
                # Handle text messages (control signals)
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
                
                # Handle binary messages (raw PCM audio data)
                elif isinstance(message, bytes):
                    if session.is_recording:
                        session.add_audio_data(message)
                        # Optional: print buffer status occasionally
                        if len(session.audio_buffer) % (16000 * 2) < 8192:
                            print(f"📊 Buffer: {len(session.audio_buffer)} samples ({len(session.audio_buffer)/16000:.1f}s)")
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
    print("🎤 Real-Time Transcription Server with Chunked Processing")
    print("="*60)
    print(f"Backend:  http://127.0.0.1:5000")
    print(f"Chunk:    {CHUNK_DURATION}s")
    print(f"Overlap:  {OVERLAP_DURATION}s")
    print(f"Sample:   {SAMPLE_RATE}Hz, {SAMPLE_WIDTH*8}-bit")
    print("="*60 + "\n")
    app.run(debug=True, port=5000, host='0.0.0.0')