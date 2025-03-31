from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import Session
from typing import Optional
import os
from dotenv import load_dotenv

from .models import Base, Hand, Action, AISuggestion, Outcome, ActionType

load_dotenv()

class DatabaseManager:
    def __init__(self):
        self.database_url = os.getenv("DATABASE_URL", "sqlite:///data/database/pokerit.db")
        self.engine = create_engine(self.database_url)
        self.SessionLocal = sessionmaker(bind=self.engine)
        
    def init_db(self):
        """Initialize the database by creating all tables."""
        Base.metadata.create_all(self.engine)
        
    def get_session(self) -> Session:
        """Get a new database session."""
        return self.SessionLocal()
        
    def create_hand(self, table_name: str, max_players: int, 
                   starting_stack: float, small_blind: float, 
                   big_blind: float) -> Hand:
        """Create a new hand record."""
        with self.get_session() as session:
            hand = Hand(
                table_name=table_name,
                max_players=max_players,
                starting_stack=starting_stack,
                small_blind=small_blind,
                big_blind=big_blind
            )
            session.add(hand)
            session.commit()
            session.refresh(hand)
            return hand
            
    def record_action(self, hand_id: int, player_name: str, 
                     action_type: ActionType, amount: Optional[float],
                     street: str, position: int) -> Action:
        """Record a player action."""
        with self.get_session() as session:
            action = Action(
                hand_id=hand_id,
                player_name=player_name,
                action_type=action_type,
                amount=amount,
                street=street,
                position=position
            )
            session.add(action)
            session.commit()
            session.refresh(action)
            return action
            
    def record_ai_suggestion(self, action_id: int, suggested_action: ActionType,
                           suggested_amount: Optional[float], confidence: float,
                           reasoning: str) -> AISuggestion:
        """Record an AI suggestion for an action."""
        with self.get_session() as session:
            suggestion = AISuggestion(
                action_id=action_id,
                suggested_action=suggested_action,
                suggested_amount=suggested_amount,
                confidence=confidence,
                reasoning=reasoning
            )
            session.add(suggestion)
            session.commit()
            session.refresh(suggestion)
            return suggestion
            
    def record_outcome(self, hand_id: int, player_name: str,
                      final_stack: float, profit_loss: float,
                      hand_rank: str) -> Outcome:
        """Record the outcome of a hand for a player."""
        with self.get_session() as session:
            outcome = Outcome(
                hand_id=hand_id,
                player_name=player_name,
                final_stack=final_stack,
                profit_loss=profit_loss,
                hand_rank=hand_rank
            )
            session.add(outcome)
            session.commit()
            session.refresh(outcome)
            return outcome
            
    def get_hand_history(self, hand_id: int) -> dict:
        """Get complete hand history including actions and outcomes."""
        with self.get_session() as session:
            hand = session.query(Hand).filter(Hand.id == hand_id).first()
            if not hand:
                return None
                
            return {
                "hand": hand,
                "actions": hand.actions,
                "outcomes": hand.outcomes
            }
            
    def get_player_stats(self, player_name: str) -> dict:
        """Get player statistics including win rate and average profit."""
        with self.get_session() as session:
            outcomes = session.query(Outcome).filter(
                Outcome.player_name == player_name
            ).all()
            
            if not outcomes:
                return {
                    "total_hands": 0,
                    "win_rate": 0,
                    "avg_profit": 0
                }
                
            winning_hands = sum(1 for o in outcomes if o.profit_loss > 0)
            
            return {
                "total_hands": len(outcomes),
                "win_rate": winning_hands / len(outcomes),
                "avg_profit": sum(o.profit_loss for o in outcomes) / len(outcomes)
            } 