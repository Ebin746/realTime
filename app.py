from flask import Flask, request, jsonify, render_template_string
from flask_cors import CORS
import whisper
import tempfile
import os
from pydub import AudioSegment

app = Flask(__name__)
CORS(app)

print("Loading Whisper model...")
model = whisper.load_model("tiny")
print("Model loaded!")

HTML_TEMPLATE = '''
<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Audio Transcription</title>
  <style>
    body {
      font-family: Arial, sans-serif;
      max-width: 600px;
      margin: 50px auto;
      padding: 20px;
      background: #f0f0f0;
    }
    .container {
      background: white;
      padding: 30px;
      border-radius: 10px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.1);
    }
    button {
      padding: 15px 30px;
      margin: 10px 5px;
      font-size: 18px;
      cursor: pointer;
      border: none;
      border-radius: 5px;
      transition: all 0.3s;
    }
    #start { background: #4CAF50; color: white; }
    #start:hover { background: #45a049; }
    #stop { background: #f44336; color: white; }
    #stop:hover { background: #da190b; }
    #start:disabled, #stop:disabled { opacity: 0.5; cursor: not-allowed; }
    .status { 
      margin: 20px 0; 
      padding: 15px; 
      border-radius: 5px;
      font-weight: bold;
    }
    .recording { background: #ffe0e0; color: #c00; }
    .processing { background: #fff4e0; color: #c80; }
    .success { background: #e0ffe0; color: #0a0; }
    .error { background: #ffe0e0; color: #c00; }
    .transcription {
      margin-top: 20px;
      padding: 20px;
      background: #f9f9f9;
      border-left: 4px solid #4CAF50;
      border-radius: 5px;
      min-height: 60px;
      font-size: 18px;
      line-height: 1.6;
    }
    .timer {
      font-size: 24px;
      font-weight: bold;
      margin: 10px 0;
    }
    .instructions {
      background: #e3f2fd;
      padding: 15px;
      border-radius: 5px;
      margin-bottom: 20px;
    }
  </style>
</head>
<body>
  <div class="container">
    <h2>🎤 Audio Transcription</h2>
    
    <div class="instructions">
      <strong>📝 Instructions:</strong>
      <ul>
        <li>Click "Start Recording" and speak clearly</li>
        <li>Speak for at least 2-3 seconds</li>
        <li>Click "Stop Recording" when done</li>
        <li>Wait for transcription to appear</li>
      </ul>
    </div>
    
    <div>
      <button id="start" onclick="startRecording()">Start Recording</button>
      <button id="stop" onclick="stopRecording()" disabled>Stop Recording</button>
    </div>
    
    <div id="timer" class="timer"></div>
    <div id="status" class="status"></div>
    <div id="transcription" class="transcription" style="display:none;"></div>
  </div>

  <script>
    let mediaRecorder;
    let audioChunks = [];
    let startTime;
    let timerInterval;

    async function startRecording() {
      try {
        const stream = await navigator.mediaDevices.getUserMedia({ 
          audio: {
            channelCount: 1,
            sampleRate: 16000
          } 
        });
        
        const mimeType = MediaRecorder.isTypeSupported('audio/webm;codecs=opus') 
          ? 'audio/webm;codecs=opus' 
          : 'audio/webm';
        
        mediaRecorder = new MediaRecorder(stream, { mimeType: mimeType });
        audioChunks = [];
        
        mediaRecorder.ondataavailable = e => {
          if (e.data.size > 0) {
            audioChunks.push(e.data);
            console.log("Audio chunk received:", e.data.size, "bytes");
          }
        };
        
        mediaRecorder.onstop = uploadAudio;
        
        mediaRecorder.start(100); // Collect data every 100ms
        startTime = Date.now();
        
        // Timer
        timerInterval = setInterval(() => {
          const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
          document.getElementById("timer").innerText = `⏱️ ${elapsed}s`;
        }, 100);
        
        document.getElementById("start").disabled = true;
        document.getElementById("stop").disabled = false;
        document.getElementById("status").className = "status recording";
        document.getElementById("status").innerText = "🔴 Recording... Speak now!";
        document.getElementById("transcription").style.display = "none";
        
      } catch (err) {
        document.getElementById("status").className = "status error";
        document.getElementById("status").innerText = "❌ Microphone access denied: " + err.message;
        console.error(err);
      }
    }

    function stopRecording() {
      if (mediaRecorder && mediaRecorder.state !== "inactive") {
        clearInterval(timerInterval);
        mediaRecorder.stop();
        mediaRecorder.stream.getTracks().forEach(track => track.stop());
        
        document.getElementById("start").disabled = false;
        document.getElementById("stop").disabled = true;
        document.getElementById("status").className = "status processing";
        document.getElementById("status").innerText = "⏳ Processing audio...";
        document.getElementById("timer").innerText = "";
      }
    }

    async function uploadAudio() {
      try {
        const mimeType = audioChunks[0]?.type || 'audio/webm';
        const blob = new Blob(audioChunks, { type: mimeType });
        
        console.log("=== UPLOAD INFO ===");
        console.log("Blob size:", blob.size, "bytes");
        console.log("Blob type:", mimeType);
        console.log("Number of chunks:", audioChunks.length);
        
        if (blob.size < 1000) {
          throw new Error("Recording too short or failed. Please speak for at least 2-3 seconds.");
        }
        
        const formData = new FormData();
        formData.append("file", blob, "audio.webm");

        console.log("Sending to server...");
        const res = await fetch("/transcribe", {
          method: "POST",
          body: formData
        });
        
        console.log("Response status:", res.status);
        
        if (!res.ok) {
          const errorText = await res.text();
          throw new Error(`Server error (${res.status}): ${errorText}`);
        }
        
        const data = await res.json();
        console.log("Server response:", data);
        
        if (data.error) {
          throw new Error(data.error);
        }
        
        document.getElementById("status").className = "status success";
        document.getElementById("status").innerText = "✅ Transcription complete!";
        document.getElementById("transcription").style.display = "block";
        document.getElementById("transcription").innerHTML = 
          "<strong>Transcription:</strong><br>" + (data.text || "(No speech detected)");
        
      } catch (err) {
        document.getElementById("status").className = "status error";
        document.getElementById("status").innerText = "❌ Error: " + err.message;
        console.error("Error details:", err);
      } finally {
        audioChunks = [];
      }
    }
  </script>
</body>
</html>
'''

@app.route("/")
def index():
    return render_template_string(HTML_TEMPLATE)

@app.route("/transcribe", methods=["POST"])
def transcribe():
    temp_path = None
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
        
        # Cleanup
        os.unlink(input_path)
        
        return jsonify({"text": result["text"]})
    
    except Exception as e:
        print(f"ERROR: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass

if __name__ == "__main__":
    print("\n" + "="*50)
    print("🎤 Audio Transcription Server")
    print("="*50)
    print("Open your browser and go to: http://127.0.0.1:5000")
    print("="*50 + "\n")
    app.run(debug=True, port=5000)