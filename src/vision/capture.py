import cv2
import numpy as np
import pyautogui
from typing import Tuple, Optional
import os
from dotenv import load_dotenv

load_dotenv()

class ScreenCapture:
    def __init__(self):
        # Parse screen capture region from environment variables
        region_str = os.getenv("SCREEN_CAPTURE_REGION", "0,0,1920,1080")
        x, y, width, height = map(int, region_str.split(","))
        self.region = (x, y, width, height)
        
    def capture_screen(self) -> np.ndarray:
        """Capture the specified region of the screen."""
        screenshot = pyautogui.screenshot(region=self.region)
        # Convert PIL image to OpenCV format
        frame = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        return frame
        
    def capture_region(self, region: Tuple[int, int, int, int]) -> np.ndarray:
        """Capture a specific region of the screen."""
        x, y, width, height = region
        screenshot = pyautogui.screenshot(region=(x, y, width, height))
        frame = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)
        return frame
        
    def save_frame(self, frame: np.ndarray, filename: str):
        """Save a captured frame to disk."""
        cv2.imwrite(filename, frame)
        
    def show_frame(self, frame: np.ndarray, window_name: str = "Screen Capture"):
        """Display a captured frame in a window."""
        cv2.imshow(window_name, frame)
        cv2.waitKey(1)
        
    def close_windows(self):
        """Close all OpenCV windows."""
        cv2.destroyAllWindows()
        
    def get_mouse_position(self) -> Tuple[int, int]:
        """Get the current mouse position."""
        return pyautogui.position()
        
    def get_screen_size(self) -> Tuple[int, int]:
        """Get the size of the screen."""
        return pyautogui.size()
        
    def is_region_visible(self, region: Tuple[int, int, int, int]) -> bool:
        """Check if a region is visible on screen."""
        screen_width, screen_height = self.get_screen_size()
        x, y, width, height = region
        
        return (0 <= x < screen_width and 
                0 <= y < screen_height and 
                0 <= x + width <= screen_width and 
                0 <= y + height <= screen_height) 