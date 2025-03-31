from datetime import datetime
from typing import Optional
from sqlalchemy import Column, Integer, String, Float, DateTime, ForeignKey, Enum
from sqlalchemy.orm import declarative_base, relationship
import enum

Base = declarative_base()

class ActionType(enum.Enum):
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    BET = "bet"
    RAISE = "raise"
    ALL_IN = "all_in"

class Hand(Base):
    __tablename__ = "hands"
    
    id = Column(Integer, primary_key=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    table_name = Column(String)
    max_players = Column(Integer)
    starting_stack = Column(Float)
    small_blind = Column(Float)
    big_blind = Column(Float)
    
    # Relationships
    actions = relationship("Action", back_populates="hand")
    outcomes = relationship("Outcome", back_populates="hand")

class Action(Base):
    __tablename__ = "actions"
    
    id = Column(Integer, primary_key=True)
    hand_id = Column(Integer, ForeignKey("hands.id"))
    player_name = Column(String)
    action_type = Column(Enum(ActionType))
    amount = Column(Float, nullable=True)
    street = Column(String)  # preflop, flop, turn, river
    position = Column(Integer)  # 0 for SB, 1 for BB, etc.
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    hand = relationship("Hand", back_populates="actions")
    ai_suggestions = relationship("AISuggestion", back_populates="action")

class AISuggestion(Base):
    __tablename__ = "ai_suggestions"
    
    id = Column(Integer, primary_key=True)
    action_id = Column(Integer, ForeignKey("actions.id"))
    suggested_action = Column(Enum(ActionType))
    suggested_amount = Column(Float, nullable=True)
    confidence = Column(Float)
    reasoning = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    action = relationship("Action", back_populates="ai_suggestions")

class Outcome(Base):
    __tablename__ = "outcomes"
    
    id = Column(Integer, primary_key=True)
    hand_id = Column(Integer, ForeignKey("hands.id"))
    player_name = Column(String)
    final_stack = Column(Float)
    profit_loss = Column(Float)
    hand_rank = Column(String)  # e.g., "Royal Flush", "Two Pair"
    timestamp = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    hand = relationship("Hand", back_populates="outcomes") 