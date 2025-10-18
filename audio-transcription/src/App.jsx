import React, { useState, useEffect, useRef } from 'react';
import styled from 'styled-components';

const Container = styled.div`
  padding: 20px;
  max-width: 800px;
  margin: 0 auto;
  font-family: system-ui, -apple-system, sans-serif;
`;

const Title = styled.h1`
  margin-bottom: 24px;
`;

const StatusBox = styled.div`
  padding: 16px;
  margin-bottom: 20px;
  background-color: #f3f4f6;
  border-radius: 8px;
  border: 1px solid #e5e7eb;
`;

const StatusRow = styled.div`
  margin-bottom: 12px;
  display: flex;
  align-items: center;
  gap: 8px;
`;

const StatusIndicator = styled.div`
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background-color: ${props => props.color};
  animation: ${props => props.isRecording ? 'pulse 2s infinite' : 'none'};
`;

const StatusLabel = styled.strong`
`;

const StatusText = styled.span`
  margin-left: 8px;
  color: #6b7280;
`;

const ConnectionStatus = styled.div`
  font-size: 14px;
  color: #6b7280;
`;

const ButtonGroup = styled.div`
  margin-bottom: 24px;
  display: flex;
  gap: 12px;
`;

const Button = styled.button`
  padding: 12px 24px;
  font-size: 16px;
  font-weight: 600;
  background-color: ${props => props.disabled ? '#e5e7eb' : props.bgColor};
  color: ${props => props.disabled ? '#9ca3af' : 'white'};
  border: none;
  border-radius: 8px;
  cursor: ${props => props.disabled ? 'not-allowed' : 'pointer'};
  transition: all 0.2s;
`;

const TranscriptionBox = styled.div`
  border: 1px solid #e5e7eb;
  border-radius: 8px;
  padding: 16px;
  min-height: 300px;
  max-height: 500px;
  overflow-y: auto;
  background-color: #ffffff;
`;

const TranscriptionTitle = styled.h3`
  margin-top: 0;
  margin-bottom: 16px;
`;

const EmptyTranscription = styled.p`
  color: #9ca3af;
  text-align: center;
  padding: 40px 20px;
`;

const TranscriptionItem = styled.div`
  padding: 12px 16px;
  margin-bottom: 12px;
  background-color: #f9fafb;
  border-left: 4px solid #22c55e;
  border-radius: 4px;
  box-shadow: 0 1px 2px rgba(0,0,0,0.05);
`;

const Timestamp = styled.div`
  font-size: 12px;
  color: #6b7280;
  margin-bottom: 6px;
  font-weight: 500;
`;

const TranscriptionText = styled.div`
  font-size: 16px;
  line-height: 1.5;
  color: #111827;
`;

const GlobalStyles = styled.div`
  @keyframes pulse {
    0%, 100% { opacity: 1; }
    50% { opacity: 0.5; }
  }
`;

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
  const isConnectingRef = useRef(false);

  useEffect(() => {
    connectWebSocket();
    
    return () => {
      cleanup();
    };
  }, []);

  const connectWebSocket = () => {
    if (isConnectingRef.current || (wsRef.current && wsRef.current.readyState === WebSocket.OPEN)) {
      console.log('Connection already exists or is in progress');
      return;
    }

    isConnectingRef.current = true;

    try {
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
        
        if (isRecordingRef.current) {
          stopRecording();
        }
        
        if (reconnectTimeoutRef.current) {
          clearTimeout(reconnectTimeoutRef.current);
        }
        
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
      
      const audioContext = new (window.AudioContext || window.webkitAudioContext)({
        sampleRate: 16000
      });
      audioContextRef.current = audioContext;
      
      const source = audioContext.createMediaStreamSource(stream);
      
      const processor = audioContext.createScriptProcessor(4096, 1, 1);
      processorRef.current = processor;
      
      isRecordingRef.current = true;
      setIsRecording(true);
      setStatus('Recording... speak now!');
      setTranscriptions([]);
      
      wsRef.current.send(JSON.stringify({ type: 'start' }));
      console.log('✓ Sent start signal to WebSocket');
      
      processor.onaudioprocess = (e) => {
        if (!isRecordingRef.current || !wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
          return;
        }
        
        const inputData = e.inputBuffer.getChannelData(0);
        
        const int16Data = new Int16Array(inputData.length);
        for (let i = 0; i < inputData.length; i++) {
          const s = Math.max(-1, Math.min(1, inputData[i]));
          int16Data[i] = s < 0 ? s * 0x8000 : s * 0x7FFF;
        }
        
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
    
    if (wsRef.current && wsRef.current.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: 'stop' }));
      console.log('✓ Sent stop signal to WebSocket');
    }
    
    setStatus('Recording stopped');
  };

  const cleanup = () => {
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
    <GlobalStyles>
      <Container>
        <Title>🎤 Real-Time Audio Transcription</Title>
        
        <StatusBox>
          <StatusRow>
            <StatusIndicator color={getStatusColor()} isRecording={isRecording} />
            <StatusLabel>Status:</StatusLabel>
            <StatusText>{status}</StatusText>
          </StatusRow>
          <ConnectionStatus>
            {wsConnected ? '✓ Connected to server' : '✗ Disconnected from server'}
          </ConnectionStatus>
        </StatusBox>
        
        <ButtonGroup>
          <Button
            onClick={startRecording}
            disabled={isRecording || !wsConnected}
            bgColor="#22c55e"
          >
            🎙️ Start Recording
          </Button>
          
          <Button
            onClick={stopRecording}
            disabled={!isRecording}
            bgColor="#ef4444"
          >
            ⏹️ Stop Recording
          </Button>
        </ButtonGroup>
        
        <TranscriptionBox>
          <TranscriptionTitle>📝 Transcriptions:</TranscriptionTitle>
          {transcriptions.length === 0 ? (
            <EmptyTranscription>
              No transcriptions yet. Click "Start Recording" and speak to see results.
            </EmptyTranscription>
          ) : (
            transcriptions.map((item, idx) => (
              <TranscriptionItem key={idx}>
                <Timestamp>{item.timestamp}</Timestamp>
                <TranscriptionText>{item.text}</TranscriptionText>
              </TranscriptionItem>
            ))
          )}
        </TranscriptionBox>
      </Container>
    </GlobalStyles>
  );
}