import sys
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                           QHBoxLayout, QLabel, QPushButton, QTextEdit,
                           QComboBox, QSpinBox, QDoubleSpinBox)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QFont, QPalette, QColor

from ..vision.capture import ScreenCapture
from ..vision.recognition import CardRecognizer
from ..game.state import GameState, Street
from ..ai.engine import AIStrategyEngine
from ..database.manager import DatabaseManager

class PokeritGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Pokerit - AI Poker Assistant")
        self.setMinimumSize(800, 600)
        
        # Initialize components
        self.screen_capture = ScreenCapture()
        self.card_recognizer = CardRecognizer()
        self.game_state = GameState()
        self.ai_engine = AIStrategyEngine()
        self.db_manager = DatabaseManager()
        
        # Setup UI
        self.setup_ui()
        
        # Setup timer for screen capture
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_game_state)
        self.timer.start(1000)  # Update every second
        
    def setup_ui(self):
        """Setup the main UI components."""
        # Create central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)
        
        # Left panel - Game state
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        
        # Game state display
        self.game_state_display = QTextEdit()
        self.game_state_display.setReadOnly(True)
        left_layout.addWidget(QLabel("Game State"))
        left_layout.addWidget(self.game_state_display)
        
        # Control panel
        control_panel = QWidget()
        control_layout = QVBoxLayout(control_panel)
        
        # Player selection
        player_layout = QHBoxLayout()
        player_layout.addWidget(QLabel("Player:"))
        self.player_combo = QComboBox()
        player_layout.addWidget(self.player_combo)
        control_layout.addLayout(player_layout)
        
        # Position selection
        position_layout = QHBoxLayout()
        position_layout.addWidget(QLabel("Position:"))
        self.position_spin = QSpinBox()
        self.position_spin.setRange(0, 9)
        position_layout.addWidget(self.position_spin)
        control_layout.addLayout(position_layout)
        
        # Stack size
        stack_layout = QHBoxLayout()
        stack_layout.addWidget(QLabel("Stack:"))
        self.stack_spin = QDoubleSpinBox()
        self.stack_spin.setRange(0, 1000000)
        self.stack_spin.setSingleStep(100)
        stack_layout.addWidget(self.stack_spin)
        control_layout.addLayout(stack_layout)
        
        # Add control panel to left layout
        left_layout.addWidget(control_panel)
        
        # Right panel - AI suggestions
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        
        # AI suggestion display
        self.ai_suggestion_display = QTextEdit()
        self.ai_suggestion_display.setReadOnly(True)
        right_layout.addWidget(QLabel("AI Suggestion"))
        right_layout.addWidget(self.ai_suggestion_display)
        
        # Action buttons
        button_layout = QHBoxLayout()
        self.start_button = QPushButton("Start Analysis")
        self.start_button.clicked.connect(self.start_analysis)
        self.stop_button = QPushButton("Stop Analysis")
        self.stop_button.clicked.connect(self.stop_analysis)
        self.stop_button.setEnabled(False)
        
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.stop_button)
        right_layout.addLayout(button_layout)
        
        # Add panels to main layout
        main_layout.addWidget(left_panel, stretch=1)
        main_layout.addWidget(right_panel, stretch=1)
        
    def update_game_state(self):
        """Update the game state from screen capture."""
        if not self.start_button.isEnabled():
            # Capture screen
            frame = self.screen_capture.capture_screen()
            
            # Detect cards and actions
            cards = self.card_recognizer.detect_cards(frame)
            actions = self.card_recognizer.detect_player_actions(frame)
            
            # Update game state
            self.update_game_state_display()
            
            # Get AI suggestion
            self.update_ai_suggestion()
            
    def update_game_state_display(self):
        """Update the game state display."""
        display_text = f"""Current Street: {self.game_state.current_street.value}
Pot: {self.game_state.pot}
Current Bet: {self.game_state.current_bet}

Community Cards: {', '.join(self.game_state.community_cards) if self.game_state.community_cards else 'None'}

Active Players:
"""
        for player in self.game_state.get_active_players():
            display_text += f"{player.name}: Stack={player.stack}, Position={player.position}\n"
            
        self.game_state_display.setText(display_text)
        
    def update_ai_suggestion(self):
        """Update the AI suggestion display."""
        if self.player_combo.currentText():
            action, amount, confidence, reasoning = self.ai_engine.get_suggestion(
                self.game_state, self.player_combo.currentText()
            )
            
            suggestion_text = f"""Suggested Action: {action.value}
Amount: {amount if amount else 'N/A'}
Confidence: {confidence:.2f}

Reasoning:
{reasoning}"""
            
            self.ai_suggestion_display.setText(suggestion_text)
            
    def start_analysis(self):
        """Start the analysis process."""
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.timer.start()
        
    def stop_analysis(self):
        """Stop the analysis process."""
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.timer.stop()
        
def main():
    app = QApplication(sys.argv)
    window = PokeritGUI()
    window.show()
    sys.exit(app.exec()) 