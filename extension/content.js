// Configuration
let captureInterval = 2000; // 2 seconds
let isCapturing = false;
let captureTimer = null;
let sessionId = null;
let webSocket = null;
let apiUrl = 'http://localhost:8000';

// Initialize when the content script is loaded
function initialize() {
  console.log('Pokerit screen capture extension initialized');
  
  // Listen for messages from the popup
  chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
    if (message.type === 'START_CAPTURE') {
      startCapture(message.sessionId, message.interval);
      sendResponse({success: true});
    } else if (message.type === 'STOP_CAPTURE') {
      stopCapture();
      sendResponse({success: true});
    } else if (message.type === 'GET_STATUS') {
      sendResponse({
        isCapturing,
        sessionId,
        captureInterval
      });
    }
    return true;
  });
  
  // Load settings from storage
  chrome.storage.local.get(['pokerit_session_id', 'pokerit_capture_interval'], (result) => {
    if (result.pokerit_session_id) {
      sessionId = result.pokerit_session_id;
    }
    if (result.pokerit_capture_interval) {
      captureInterval = result.pokerit_capture_interval;
    }
  });
}

// Start screen capture
function startCapture(newSessionId, interval) {
  if (isCapturing) {
    stopCapture();
  }
  
  sessionId = newSessionId || sessionId || `session_${Math.random().toString(36).substring(2, 11)}`;
  captureInterval = interval || captureInterval;
  
  // Save settings
  chrome.storage.local.set({
    pokerit_session_id: sessionId,
    pokerit_capture_interval: captureInterval
  });
  
  // Connect to WebSocket
  connectWebSocket();
  
  // Start capture timer
  isCapturing = true;
  captureTimer = setInterval(captureScreen, captureInterval);
  console.log(`Started screen capture with session ${sessionId}`);
}

// Stop screen capture
function stopCapture() {
  if (captureTimer) {
    clearInterval(captureTimer);
    captureTimer = null;
  }
  
  if (webSocket) {
    webSocket.close();
    webSocket = null;
  }
  
  isCapturing = false;
  console.log('Stopped screen capture');
}

// Connect to WebSocket server
function connectWebSocket() {
  if (webSocket) {
    webSocket.close();
  }
  
  webSocket = new WebSocket(`ws://${apiUrl.replace('http://', '')}/ws/${sessionId}`);
  
  webSocket.onopen = () => {
    console.log('Connected to Pokerit server');
  };
  
  webSocket.onerror = (error) => {
    console.error('WebSocket error:', error);
  };
  
  webSocket.onclose = () => {
    console.log('Disconnected from Pokerit server');
    // Try to reconnect after a delay
    setTimeout(() => {
      if (isCapturing) {
        connectWebSocket();
      }
    }, 5000);
  };
}

// Capture screen and send to server
function captureScreen() {
  if (!isCapturing || !webSocket || webSocket.readyState !== WebSocket.OPEN) {
    return;
  }
  
  // Use Chrome API to capture visible tab
  chrome.runtime.sendMessage({type: 'CAPTURE_SCREEN'}, (response) => {
    if (response && response.imageData) {
      // Send the image data to the server
      webSocket.send(JSON.stringify({
        type: 'screen_capture',
        sessionId: sessionId,
        imageData: response.imageData,
        timestamp: Date.now()
      }));
    }
  });
}

// Initialize the extension
initialize(); 