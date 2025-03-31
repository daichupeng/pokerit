from dataclasses import dataclass
from typing import List, Dict, Optional
from enum import Enum
from datetime import datetime

class Street(Enum):
    PREFLOP = "preflop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"

@dataclass
class Player:
    name: str
    stack: float
    position: int
    is_active: bool = True
    cards: List[str] = None  # List of card strings (e.g., ["Ah", "Ks"])
    
@dataclass
class Action:
    player: str
    action_type: str  # fold, check, call, bet, raise
    amount: Optional[float]
    street: Street
    timestamp: datetime

class GameState:
    def __init__(self):
        self.players: Dict[str, Player] = {}
        self.community_cards: List[str] = []
        self.current_street: Street = Street.PREFLOP
        self.pot: float = 0
        self.current_bet: float = 0
        self.small_blind: float = 0
        self.big_blind: float = 0
        self.dealer_position: int = 0
        self.action_history: List[Action] = []
        self.last_action: Optional[Action] = None
        
    def add_player(self, name: str, stack: float, position: int):
        """Add a player to the game."""
        self.players[name] = Player(name=name, stack=stack, position=position)
        
    def remove_player(self, name: str):
        """Remove a player from the game."""
        if name in self.players:
            del self.players[name]
            
    def set_blinds(self, small_blind: float, big_blind: float):
        """Set the small and big blinds."""
        self.small_blind = small_blind
        self.big_blind = big_blind
        
    def set_dealer_position(self, position: int):
        """Set the dealer position."""
        self.dealer_position = position
        
    def deal_player_cards(self, player: str, cards: List[str]):
        """Deal cards to a player."""
        if player in self.players:
            self.players[player].cards = cards
            
    def deal_community_cards(self, cards: List[str]):
        """Deal community cards."""
        self.community_cards = cards
        
    def record_action(self, player: str, action_type: str, 
                     amount: Optional[float], street: Street):
        """Record a player action."""
        action = Action(
            player=player,
            action_type=action_type,
            amount=amount,
            street=street,
            timestamp=datetime.now()
        )
        self.action_history.append(action)
        self.last_action = action
        
        # Update pot and player stack
        if action_type in ["bet", "call", "raise"] and amount:
            self.pot += amount
            if player in self.players:
                self.players[player].stack -= amount
                
    def advance_street(self):
        """Advance to the next street."""
        if self.current_street == Street.PREFLOP:
            self.current_street = Street.FLOP
        elif self.current_street == Street.FLOP:
            self.current_street = Street.TURN
        elif self.current_street == Street.TURN:
            self.current_street = Street.RIVER
        elif self.current_street == Street.RIVER:
            self.current_street = Street.SHOWDOWN
            
    def get_active_players(self) -> List[Player]:
        """Get list of active players."""
        return [p for p in self.players.values() if p.is_active]
        
    def get_player_position(self, player: str) -> Optional[int]:
        """Get a player's position."""
        return self.players.get(player, None).position if player in self.players else None
        
    def get_player_stack(self, player: str) -> Optional[float]:
        """Get a player's current stack."""
        return self.players.get(player, None).stack if player in self.players else None
        
    def is_player_active(self, player: str) -> bool:
        """Check if a player is still active in the hand."""
        return self.players.get(player, None).is_active if player in self.players else False
        
    def get_action_history(self, player: Optional[str] = None) -> List[Action]:
        """Get action history, optionally filtered by player."""
        if player:
            return [a for a in self.action_history if a.player == player]
        return self.action_history
        
    def get_current_bet_to_call(self) -> float:
        """Get the amount needed to call the current bet."""
        return self.current_bet
        
    def reset_hand(self):
        """Reset the game state for a new hand."""
        self.community_cards = []
        self.current_street = Street.PREFLOP
        self.pot = 0
        self.current_bet = 0
        self.action_history = []
        self.last_action = None
        
        # Reset player cards but keep stacks
        for player in self.players.values():
            player.cards = None
            player.is_active = True 