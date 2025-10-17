import React, { useState, useEffect, useRef } from 'react';

export default function AudioTranscription() {
  const [isRecording, setIsRecording] = useState(false);
  const [status, setStatus] = useState({ message: '', type: '' });
  const [transcription, setTranscription] = useState('');
  const [timer, setTimer] = useState(0);
  
  const mediaRecorderRef = useRef(null);
  const audioChunksRef = useRef([]);
  const timerIntervalRef = useRef(null);
  const startTimeRef = useRef(null);

  useEffect(() => {
    return () => {
      if (timerIntervalRef.current) {
        clearInterval(timerIntervalRef.current);
      }
      if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
        mediaRecorderRef.current.stream.getTracks().forEach(track => track.stop());
      }
    };
  }, []);

  const startRecording = async () => {
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

      mediaRecorderRef.current = new MediaRecorder(stream, { mimeType });
      audioChunksRef.current = [];

      mediaRecorderRef.current.ondataavailable = (e) => {
        if (e.data.size > 0) {
          audioChunksRef.current.push(e.data);
          console.log("Audio chunk received:", e.data.size, "bytes");
        }
      };

      mediaRecorderRef.current.onstop = uploadAudio;
      mediaRecorderRef.current.start(100);

      startTimeRef.current = Date.now();
      timerIntervalRef.current = setInterval(() => {
        const elapsed = ((Date.now() - startTimeRef.current) / 1000).toFixed(1);
        setTimer(parseFloat(elapsed));
      }, 100);

      setIsRecording(true);
      setStatus({ message: '🔴 Recording... Speak now!', type: 'recording' });
      setTranscription('');

    } catch (err) {
      setStatus({ 
        message: `❌ Microphone access denied: ${err.message}`, 
        type: 'error' 
      });
      console.error(err);
    }
  };

  const stopRecording = () => {
    if (mediaRecorderRef.current && mediaRecorderRef.current.state !== 'inactive') {
      clearInterval(timerIntervalRef.current);
      mediaRecorderRef.current.stop();
      mediaRecorderRef.current.stream.getTracks().forEach(track => track.stop());

      setIsRecording(false);
      setStatus({ message: '⏳ Processing audio...', type: 'processing' });
      setTimer(0);
    }
  };

  const uploadAudio = async () => {
    try {
      const mimeType = audioChunksRef.current[0]?.type || 'audio/webm';
      const blob = new Blob(audioChunksRef.current, { type: mimeType });

      console.log("=== UPLOAD INFO ===");
      console.log("Blob size:", blob.size, "bytes");
      console.log("Blob type:", mimeType);
      console.log("Number of chunks:", audioChunksRef.current.length);

      if (blob.size < 1000) {
        throw new Error("Recording too short or failed. Please speak for at least 2-3 seconds.");
      }

      const formData = new FormData();
      formData.append("file", blob, "audio.webm");

      console.log("Sending to server...");
      const res = await fetch("http://127.0.0.1:5000/transcribe", {
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

      setStatus({ message: '✅ Transcription complete!', type: 'success' });
      setTranscription(data.text || "(No speech detected)");

    } catch (err) {
      setStatus({ message: `❌ Error: ${err.message}`, type: 'error' });
      console.error("Error details:", err);
    } finally {
      audioChunksRef.current = [];
    }
  };

  const getStatusClass = () => {
    switch (status.type) {
      case 'recording': return 'bg-red-100 text-red-700';
      case 'processing': return 'bg-yellow-100 text-yellow-700';
      case 'success': return 'bg-green-100 text-green-700';
      case 'error': return 'bg-red-100 text-red-700';
      default: return '';
    }
  };

  return (
    <div className="min-h-screen bg-gray-100 py-12 px-4">
      <div className="max-w-2xl mx-auto bg-white rounded-xl shadow-lg p-8">
        <h2 className="text-3xl font-bold mb-6 text-gray-800">🎤 Audio Transcription</h2>

        {/* Instructions */}
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4 mb-6">
          <p className="font-semibold mb-2 text-gray-800">📝 Instructions:</p>
          <ul className="list-disc list-inside space-y-1 text-gray-700">
            <li>Click "Start Recording" and speak clearly</li>
            <li>Speak for at least 2-3 seconds</li>
            <li>Click "Stop Recording" when done</li>
            <li>Wait for transcription to appear</li>
          </ul>
        </div>

        {/* Buttons */}
        <div className="flex gap-3 mb-6">
          <button
            onClick={startRecording}
            disabled={isRecording}
            className="flex-1 bg-green-500 hover:bg-green-600 text-white font-semibold py-4 px-6 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-lg"
          >
            Start Recording
          </button>
          <button
            onClick={stopRecording}
            disabled={!isRecording}
            className="flex-1 bg-red-500 hover:bg-red-600 text-white font-semibold py-4 px-6 rounded-lg disabled:opacity-50 disabled:cursor-not-allowed transition-colors text-lg"
          >
            Stop Recording
          </button>
        </div>

        {/* Timer */}
        {timer > 0 && (
          <div className="text-3xl font-bold text-center mb-4 text-gray-700">
            ⏱️ {timer}s
          </div>
        )}

        {/* Status */}
        {status.message && (
          <div className={`p-4 rounded-lg font-semibold mb-4 ${getStatusClass()}`}>
            {status.message}
          </div>
        )}

        {/* Transcription */}
        {transcription && (
          <div className="bg-gray-50 border-l-4 border-green-500 p-6 rounded-lg">
            <p className="font-semibold mb-2 text-gray-800">Transcription:</p>
            <p className="text-lg text-gray-700 leading-relaxed">{transcription}</p>
          </div>
        )}
      </div>
    </div>
  );
}