// Popup script for Pokerit Screen Capture extension

// DOM elements
const form = document.getElementById('capture-form');
const sessionInput = document.getElementById('session-input');
const intervalInput = document.getElementById('interval-input');
const actionButton = document.getElementById('action-button');
const statusValue = document.getElementById('status-value');
const sessionIdDisplay = document.getElementById('session-id');

// State
let isCapturing = false;
let currentTab = null;

// Initialize popup
document.addEventListener('DOMContentLoaded', () => {
  // Get current tab
  chrome.tabs.query({active: true, currentWindow: true}, (tabs) => {
    if (tabs && tabs.length > 0) {
      currentTab = tabs[0];
      
      // Get current status from content script
      chrome.tabs.sendMessage(currentTab.id, {type: 'GET_STATUS'}, (response) => {
        if (response) {
          updateUIFromStatus(response);
        } else {
          // Content script might not be initialized yet
          console.log('No response from content script');
        }
      });
    }
  });
  
  // Load saved settings
  chrome.storage.local.get(['pokerit_session_id', 'pokerit_capture_interval'], (result) => {
    if (result.pokerit_session_id) {
      sessionInput.value = result.pokerit_session_id;
    }
    if (result.pokerit_capture_interval) {
      intervalInput.value = result.pokerit_capture_interval;
    }
  });
  
  // Set up form submission
  form.addEventListener('submit', handleFormSubmit);
});

// Handle form submission
function handleFormSubmit(event) {
  event.preventDefault();
  
  if (isCapturing) {
    stopCapture();
  } else {
    startCapture();
  }
}

// Start screen capture
function startCapture() {
  if (!currentTab) return;
  
  const sessionId = sessionInput.value.trim() || null;
  const interval = parseInt(intervalInput.value, 10) || 2000;
  
  // Save settings
  chrome.storage.local.set({
    pokerit_session_id: sessionId,
    pokerit_capture_interval: interval
  });
  
  // Send message to content script
  chrome.tabs.sendMessage(currentTab.id, {
    type: 'START_CAPTURE',
    sessionId,
    interval
  }, (response) => {
    if (response && response.success) {
      updateCaptureStatus(true, sessionId);
    }
  });
}

// Stop screen capture
function stopCapture() {
  if (!currentTab) return;
  
  chrome.tabs.sendMessage(currentTab.id, {
    type: 'STOP_CAPTURE'
  }, (response) => {
    if (response && response.success) {
      updateCaptureStatus(false);
    }
  });
}

// Update UI based on capture status
function updateCaptureStatus(capturing, sessionId = null) {
  isCapturing = capturing;
  
  if (capturing) {
    actionButton.textContent = 'Stop Capture';
    actionButton.classList.add('stop');
    statusValue.textContent = 'Connected';
    statusValue.classList.remove('status-disconnected');
    statusValue.classList.add('status-connected');
    
    if (sessionId) {
      sessionIdDisplay.textContent = sessionId;
    }
  } else {
    actionButton.textContent = 'Start Capture';
    actionButton.classList.remove('stop');
    statusValue.textContent = 'Disconnected';
    statusValue.classList.remove('status-connected');
    statusValue.classList.add('status-disconnected');
  }
}

// Update UI from status response
function updateUIFromStatus(status) {
  if (status.isCapturing) {
    updateCaptureStatus(true, status.sessionId);
    
    if (status.sessionId) {
      sessionInput.value = status.sessionId;
    }
    if (status.captureInterval) {
      intervalInput.value = status.captureInterval;
    }
  }
} 