import React, { useState, useEffect, useRef } from 'react';

export default function RealtimeTranscription() {
  const [isRecording, setIsRecording] = useState(false);
  const [status, setStatus] = useState('');
  const [transcriptions, setTranscriptions] = useState([]);
  const [wsConnected, setWsConnected] = useState(false);
  
  const wsRef = useRef(null);
  const audioContextRef = useRef(null);
  const processorRef = useRef(null);
  const streamRef = useRef(null);
  const isRecordingRef = useRef(false);
  const reconnectTimeoutRef = useRef(null);
  const isConnectingRef = useRef(false); // Prevent duplicate connections

  useEffect(() => {
    connectWebSocket();
    
    return () => {
      cleanup();
    };
  }, []);

  const connectWebSocket = () => {
    // Prevent multiple simultaneous connection attempts
    if (isConnectingRef.current || (wsRef.current && wsRef.current.readyState === WebSocket.OPEN)) {
      console.log('Connection already exists or is in progress');
      return;
    }

    isConnectingRef.current = true;

    try {
      // Close existing connection if any
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }

      const ws = new WebSocket('ws://127.0.0.1:5000/transcribe');
      
      ws.onopen = () => {
        console.log('✓ WebSocket connected');
        isConnectingRef.current = false;
        setWsConnected(true);
        setStatus('Connected to server');
      };
      
      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          console.log('Received:', data);
          
          if (data.type === 'transcription') {
            setTranscriptions(prev => [...prev, {
              text: data.text,
              timestamp: new Date().toLocaleTimeString()
            }]);
          } else if (data.type === 'error') {
            setStatus('Error: ' + data.message);
            console.error('Server error:', data.message);
          } else if (data.type === 'status') {
            setStatus(data.message);
          }
        } catch (err) {
          console.error('Error parsing message:', err);
        }
      };
      
      ws.onerror = (error) => {
        console.error('✗ WebSocket error:', error);
        setStatus('Connection error');
        isConnectingRef.current = false;
      };
      
      ws.onclose = () => {
        console.log('✗ WebSocket closed');
        isConnectingRef.current = false;
        setWsConnected(false);
        setStatus('Disconnected');
        
        // Stop recording if active
        if (isRecordingRef.current) {
          stopRecording();
        }
        
        // Clear any existing reconnect timeout
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
        }
        
        // Attempt to reconnect after 3 seconds
        reconnectTimeoutRef.current = setTimeout(() => {
          console.log('Attempting to reconnect...');
          connectWebSocket();
        }, 3000);
      };
      
      wsRef.current = ws;
    } catch (error) {
      console.error('Failed to connect:', error);
      setStatus('Failed to connect');
      isConnectingRef.current = false;
    }
  };

  const startRecording = async () => {
    try {
      // Verify WebSocket is connected
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        setStatus('WebSocket not connected. Please wait...');
        return;
      }

      const stream = await navigator.mediaDevices.getUserMedia({
        audio: {
          channelCount: 1,
          sampleRate: 16000,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true
        }
      });
      
      streamRef.current = stream;
      
      // Create AudioContext
      const audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000
      });
      audioContextRef.current = audioContext;
      
      const source = audioContext.createMediaStreamSource(stream);
      
      // Create ScriptProcessor for raw PCM capture
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;
      
      // Set recording state BEFORE setting up the processor
      isRecordingRef.current = true;
      setIsRecording(true);
      setStatus('Recording... speak now!');
      setTranscriptions([]);
      
      // Send start signal FIRST
      wsRef.current.send(JSON.stringify({ type: 'start' }));
      console.log('✓ Sent start signal to WebSocket');
      
      processor.onaudioprocess = (e) => {
        // Use ref instead of state to avoid stale closure
        if (!isRecordingRef.current || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
          return;
        }
        
        const inputData = e.inputBuffer.getChannelData(0);
        
        // Convert Float32 to Int16
        const int16Data = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]));
          int16Data[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        
        // Send raw PCM data
        try {
          wsRef.current.send(int16Data.buffer);
        } catch (err) {
          console.error('Error sending audio data:', err);
        }
      };
      
      source.connect(processor);
      processor.connect(audioContext.destination);
      
    } catch (error) {
      console.error('Microphone error:', error);
      setStatus('Microphone access denied: ' + error.message);
      isRecordingRef.current = false;
      setIsRecording(false);
    }
  };

  const stopRecording = () => {
    isRecordingRef.current = false;
    setIsRecording(false);
    
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }
    
    if (audioContextRef.current) {
      audioContextRef.current.close();
      audioContextRef.current = null;
    }
    
    if (streamRef.current) {
      streamRef.current.getTracks().forEach(track => track.stop());
      streamRef.current = null;
    }
    
    // Send stop signal
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop' }));
      console.log('✓ Sent stop signal to WebSocket');
    }
    
    setStatus('Recording stopped');
  };

  const cleanup = () => {
    // Clear reconnect timeout
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
    }
    
    if (isRecordingRef.current) {
      stopRecording();
    }
    
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
  };

  const getStatusColor = () => {
    if (isRecording) return '#ef4444';
    if (wsConnected) return '#22c55e';
    return '#9ca3af';
  };

  return (
    <div style={{ padding: '20px', maxWidth: '800px', margin: '0 auto', fontFamily: 'system-ui, -apple-system, sans-serif' }}>
      <h1 style={{ marginBottom: '24px' }}>🎤 Real-Time Audio Transcription</h1>
      
      <div style={{ 
        padding: '16px', 
        marginBottom: '20px', 
        backgroundColor: '#f3f4f6',
        borderRadius: '8px',
        border: '1px solid #e5e7eb'
      }}>
        <div style={{ marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <div style={{ 
            width: '10px',
            height: '10px',
            borderRadius: '50%',
            backgroundColor: getStatusColor(),
            animation: isRecording ? 'pulse 2s infinite' : 'none'
          }} />
          <strong>Status:</strong> 
          <span style={{ marginLeft: '8px', color: '#6b7280' }}>{status}</span>
        </div>
        <div style={{ fontSize: '14px', color: '#6b7280' }}>
          {wsConnected ? '✓ Connected to server' : '✗ Disconnected from server'}
        </div>
      </div>
      
      <div style={{ marginBottom: '24px', display: 'flex', gap: '12px' }}>
        <button
          onClick={startRecording}
          disabled={isRecording || !wsConnected}
          style={{
            padding: '12px 24px',
            fontSize: '16px',
            fontWeight: '600',
            backgroundColor: isRecording || !wsConnected ? '#e5e7eb' : '#22c55e',
            color: isRecording || !wsConnected ? '#9ca3af' : 'white',
            border: 'none',
            borderRadius: '8px',
            cursor: isRecording || !wsConnected ? 'not-allowed' : 'pointer',
            transition: 'all 0.2s'
          }}
        >
          🎙️ Start Recording
        </button>
        
        <button
          onClick={stopRecording}
          disabled={!isRecording}
          style={{
            padding: '12px 24px',
            fontSize: '16px',
            fontWeight: '600',
            backgroundColor: !isRecording ? '#e5e7eb' : '#ef4444',
            color: !isRecording ? '#9ca3af' : 'white',
            border: 'none',
            borderRadius: '8px',
            cursor: !isRecording ? 'not-allowed' : 'pointer',
            transition: 'all 0.2s'
          }}
        >
          ⏹️ Stop Recording
        </button>
      </div>
      
      <div style={{
        border: '1px solid #e5e7eb',
        borderRadius: '8px',
        padding: '16px',
        minHeight: '300px',
        maxHeight: '500px',
        overflowY: 'auto',
        backgroundColor: '#ffffff'
      }}>
        <h3 style={{ marginTop: '0', marginBottom: '16px' }}>📝 Transcriptions:</h3>
        {transcriptions.length === 0 ? (
          <p style={{ color: '#9ca3af', textAlign: 'center', padding: '40px 20px' }}>
            No transcriptions yet. Click "Start Recording" and speak to see results.
          </p>
        ) : (
          transcriptions.map((item, idx) => (
            <div key={idx} style={{
              padding: '12px 16px',
              marginBottom: '12px',
              backgroundColor: '#f9fafb',
              borderLeft: '4px solid #22c55e',
              borderRadius: '4px',
              boxShadow: '0 1px 2px rgba(0,0,0,0.05)'
            }}>
              <div style={{ fontSize: '12px', color: '#6b7280', marginBottom: '6px', fontWeight: '500' }}>
                {item.timestamp}
              </div>
              <div style={{ fontSize: '16px', lineHeight: '1.5', color: '#111827' }}>
                {item.text}
              </div>
            </div>
          ))
        )}
      </div>
      
      <style>
        {`
          @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.5; }
          }
        `}
      </style>
    </div>
  );
}