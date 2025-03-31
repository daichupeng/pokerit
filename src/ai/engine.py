from typing import Dict, List, Optional, Tuple
import anthropic
import os
from dotenv import load_dotenv
from ..game.state import GameState, Street, Action
from ..database.models import ActionType

load_dotenv()

class AIStrategyEngine:
    def __init__(self):
        self.client = anthropic.Anthropic(
            api_key=os.getenv("CLAUDE_API_KEY")
        )
        self.model = os.getenv("AI_MODEL", "claude-3-sonnet-20240229")
        self.temperature = float(os.getenv("AI_TEMPERATURE", "0.7"))
        self.max_tokens = int(os.getenv("MAX_TOKENS", "1000"))
        
    def get_suggestion(self, game_state: GameState, player_name: str) -> Tuple[ActionType, Optional[float], float, str]:
        """Get AI suggestion for the current game state."""
        # Prepare the prompt
        prompt = self._create_prompt(game_state, player_name)
        
        # Get response from Claude
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        # Parse the response
        return self._parse_response(response.content[0].text)
        
    def _create_prompt(self, game_state: GameState, player_name: str) -> str:
        """Create a prompt for Claude with the current game state."""
        prompt = f"""You are an expert poker player. Analyze the following situation and suggest the best action:

Current Street: {game_state.current_street.value}
Your Position: {game_state.get_player_position(player_name)}
Your Stack: {game_state.get_player_stack(player_name)}
Your Cards: {game_state.players[player_name].cards if player_name in game_state.players else 'Unknown'}
Community Cards: {game_state.community_cards}
Current Pot: {game_state.pot}
Current Bet to Call: {game_state.get_current_bet_to_call()}

Recent Actions:
{self._format_action_history(game_state.get_action_history())}

Active Players:
{self._format_active_players(game_state.get_active_players())}

Please provide your suggestion in the following format:
ACTION: [fold/check/call/bet/raise/all_in]
AMOUNT: [amount if applicable, otherwise 'None']
CONFIDENCE: [0.0-1.0]
REASONING: [your explanation]"""
        
        return prompt
        
    def _format_action_history(self, actions: List[Action]) -> str:
        """Format action history for the prompt."""
        if not actions:
            return "No actions yet"
            
        return "\n".join([
            f"{action.player}: {action.action_type} {action.amount if action.amount else ''} ({action.street.value})"
            for action in actions[-5:]  # Only include last 5 actions
        ])
        
    def _format_active_players(self, players: List[Dict]) -> str:
        """Format active players for the prompt."""
        return "\n".join([
            f"{player.name}: Stack={player.stack}, Position={player.position}"
            for player in players
        ])
        
    def _parse_response(self, response: str) -> Tuple[ActionType, Optional[float], float, str]:
        """Parse Claude's response into structured data."""
        lines = response.strip().split("\n")
        action = None
        amount = None
        confidence = 0.0
        reasoning = ""
        
        for line in lines:
            if line.startswith("ACTION:"):
                action = ActionType(line.split(":")[1].strip().upper())
            elif line.startswith("AMOUNT:"):
                amount_str = line.split(":")[1].strip()
                amount = float(amount_str) if amount_str.lower() != "none" else None
            elif line.startswith("CONFIDENCE:"):
                confidence = float(line.split(":")[1].strip())
            elif line.startswith("REASONING:"):
                reasoning = line.split(":")[1].strip()
                
        return action, amount, confidence, reasoning
        
    def analyze_hand_history(self, hand_history: List[Action], player_name: str) -> str:
        """Analyze a completed hand and provide feedback."""
        prompt = f"""Analyze this completed poker hand and provide feedback for {player_name}:

{self._format_action_history(hand_history)}

Please provide feedback in the following format:
STRENGTHS: [list of good decisions]
WEAKNESSES: [list of areas for improvement]
SUGGESTIONS: [specific suggestions for improvement]"""
        
        response = self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            temperature=self.temperature,
            messages=[{
                "role": "user",
                "content": prompt
            }]
        )
        
        return response.content[0].text 