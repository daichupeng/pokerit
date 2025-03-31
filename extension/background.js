// Background script for Pokerit Screen Capture extension

// Handle messages from content script
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  if (message.type === 'CAPTURE_SCREEN') {
    captureVisibleTab(sender.tab.windowId)
      .then(imageData => {
        sendResponse({imageData});
      })
      .catch(error => {
        console.error('Error capturing screen:', error);
        sendResponse({error: error.message});
      });
    return true; // Indicate async response
  }
});

// Capture visible tab as image data URI
async function captureVisibleTab(windowId) {
  try {
    const dataUrl = await chrome.tabs.captureVisibleTab(windowId, {format: 'jpeg', quality: 70});
    return dataUrl;
  } catch (error) {
    console.error('Error in captureVisibleTab:', error);
    throw error;
  }
}

// Handle extension icon click
chrome.action.onClicked.addListener((tab) => {
  // Open popup
  chrome.action.setPopup({popup: 'popup.html'});
});

console.log('Pokerit background script initialized'); 