from flask import Flask, request, jsonify
from flask_cors import CORS
import whisper
import tempfile
import os
from pydub import AudioSegment

app = Flask(__name__)
CORS(app)  # Allow requests from Vite dev server

print("Loading Whisper model...")
model = whisper.load_model("tiny")
print("Model loaded!")

@app.route("/transcribe", methods=["POST"])
def transcribe():
    temp_path = None
    input_path = None
    try:
        print("\n=== TRANSCRIBE REQUEST ===")
        
        if "file" not in request.files:
            print("ERROR: No file in request")
            return jsonify({"error": "No file provided"}), 400
        
        file = request.files["file"]
        print(f"File received: {file.filename}, Content-Type: {file.content_type}")
        
        # Save uploaded file temporarily
        with tempfile.NamedTemporaryFile(suffix=".webm", delete=False) as temp_input:
            file.save(temp_input.name)
            input_path = temp_input.name
            print(f"Saved to: {input_path}")
        
        # Convert to WAV
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_wav:
            temp_path = temp_wav.name
        
        print("Converting audio...")
        audio = AudioSegment.from_file(input_path)
        print(f"Audio duration: {len(audio)/1000:.2f} seconds")
        
        audio = audio.set_channels(1).set_frame_rate(16000).set_sample_width(2)
        audio.export(temp_path, format="wav")
        
        print("Transcribing...")
        result = model.transcribe(temp_path, language=None, fp16=False)
        
        print(f"Result: {result['text']}")
        print("=== DONE ===\n")
        
        return jsonify({"text": result["text"]})
    
    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    
    finally:
        # Cleanup
        if input_path and os.path.exists(input_path):
            try:
                os.unlink(input_path)
            except:
                pass
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass

if __name__ == "__main__":
    print("\n" + "="*50)
    print("🎤 Audio Transcription Server")
    print("="*50)
    print("Backend running on: http://127.0.0.1:5000")
    print("="*50 + "\n")
    app.run(debug=True, port=5000, host='0.0.0.0')