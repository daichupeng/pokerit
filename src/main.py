import os
from fastapi import FastAPI, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from typing import List, Dict, Optional

from .database.manager import DatabaseManager
from .ai.engine import AIStrategyEngine
from .game.state import GameState, Street

# Initialize FastAPI app
app = FastAPI(
    title="Pokerit",
    description="AI-powered poker analysis tool",
    version="0.1.0"
)

# Add CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Restrict in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize services
db_manager = DatabaseManager()
ai_engine = AIStrategyEngine()
game_states: Dict[str, GameState] = {}  # Store game states by session_id

# WebSocket connections
active_connections: Dict[str, WebSocket] = {}

# Mount static files (for frontend)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Setup database
@app.on_event("startup")
async def startup_db_client():
    db_manager.init_db()

# WebSocket endpoint for real-time updates
@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    await websocket.accept()
    active_connections[session_id] = websocket
    
    # Create game state if it doesn't exist
    if session_id not in game_states:
        game_states[session_id] = GameState()
    
    try:
        while True:
            # Receive updates from client
            data = await websocket.receive_json()
            
            # Process the update
            if data["type"] == "game_state_update":
                # Update game state based on image processing results
                updated_state = process_game_state_update(session_id, data["data"])
                
                # Get AI suggestion
                if "player_name" in data:
                    suggestion = ai_engine.get_suggestion(
                        game_states[session_id], 
                        data["player_name"]
                    )
                    # Send AI suggestion back to client
                    await websocket.send_json({
                        "type": "ai_suggestion",
                        "data": {
                            "action": suggestion[0].value,
                            "amount": suggestion[1],
                            "confidence": suggestion[2],
                            "reasoning": suggestion[3]
                        }
                    })
            
            # Send updated game state to client
            await websocket.send_json({
                "type": "game_state",
                "data": format_game_state(game_states[session_id])
            })
    
    except WebSocketDisconnect:
        # Clean up when client disconnects
        if session_id in active_connections:
            del active_connections[session_id]

# Routes for REST API
@app.get("/")
async def root():
    return {"message": "Welcome to Pokerit API"}

@app.post("/analyze-image")
async def analyze_image():
    # This would be implemented in a real app to receive and process images
    # from the client browser extension
    return {"message": "Image analysis endpoint"}

@app.get("/hand-history/{hand_id}")
async def get_hand_history(hand_id: int):
    history = db_manager.get_hand_history(hand_id)
    if not history:
        raise HTTPException(status_code=404, detail="Hand not found")
    return history

@app.get("/player-stats/{player_name}")
async def get_player_stats(player_name: str):
    stats = db_manager.get_player_stats(player_name)
    return stats

# Helper functions
def process_game_state_update(session_id: str, data: dict) -> GameState:
    """Process game state updates from client image recognition."""
    # This would integrate with the card recognition system
    # For now, we just update the game state with the data provided
    game_state = game_states[session_id]
    
    # Example update logic
    if "community_cards" in data:
        game_state.deal_community_cards(data["community_cards"])
    
    if "player_cards" in data:
        for player, cards in data["player_cards"].items():
            game_state.deal_player_cards(player, cards)
    
    if "actions" in data:
        for action in data["actions"]:
            game_state.record_action(
                player=action["player"],
                action_type=action["action_type"],
                amount=action.get("amount"),
                street=Street(action["street"])
            )
    
    return game_state

def format_game_state(game_state: GameState) -> dict:
    """Format game state for client consumption."""
    return {
        "street": game_state.current_street.value,
        "pot": game_state.pot,
        "community_cards": game_state.community_cards,
        "current_bet": game_state.current_bet,
        "players": [
            {
                "name": p.name,
                "stack": p.stack,
                "position": p.position,
                "is_active": p.is_active,
                "cards": p.cards if p.cards else []
            }
            for p in game_state.get_active_players()
        ],
        "last_action": {
            "player": game_state.last_action.player,
            "action": game_state.last_action.action_type,
            "amount": game_state.last_action.amount,
            "street": game_state.last_action.street.value
        } if game_state.last_action else None
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("src.main:app", host="0.0.0.0", port=8000, reload=True) 