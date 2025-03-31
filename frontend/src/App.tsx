import React, { useState, useEffect, useRef } from 'react';
import axios from 'axios';

// Define types
interface PlayerInfo {
  name: string;
  stack: number;
  position: number;
  is_active: boolean;
  cards: string[];
}

interface GameState {
  street: string;
  pot: number;
  community_cards: string[];
  current_bet: number;
  players: PlayerInfo[];
  last_action: {
    player: string;
    action: string;
    amount: number | null;
    street: string;
  } | null;
}

interface AISuggestion {
  action: string;
  amount: number | null;
  confidence: number;
  reasoning: string;
}

const App: React.FC = () => {
  // State
  const [gameState, setGameState] = useState<GameState | null>(null);
  const [suggestion, setSuggestion] = useState<AISuggestion | null>(null);
  const [playerName, setPlayerName] = useState<string>('');
  const [sessionId, setSessionId] = useState<string>('');
  const [isConnected, setIsConnected] = useState<boolean>(false);
  const [captureActive, setCaptureActive] = useState<boolean>(false);
  const [captureInterval, setCaptureInterval] = useState<number>(2000); // 2 seconds
  
  // WebSocket ref
  const ws = useRef<WebSocket | null>(null);

  // Generate a session ID when the component mounts
  useEffect(() => {
    const newSessionId = `session_${Math.random().toString(36).substring(2, 11)}`;
    setSessionId(newSessionId);
  }, []);

  // Connect to WebSocket when sessionId changes
  useEffect(() => {
    if (!sessionId) return;
    
    // Close existing connection
    if (ws.current) {
      ws.current.close();
    }
    
    // Create new connection
    ws.current = new WebSocket(`ws://localhost:8000/ws/${sessionId}`);
    
    // Set up event handlers
    ws.current.onopen = () => {
      console.log('Connected to WebSocket');
      setIsConnected(true);
    };
    
    ws.current.onmessage = (event) => {
      const data = JSON.parse(event.data);
      
      if (data.type === 'game_state') {
        setGameState(data.data);
      } else if (data.type === 'ai_suggestion') {
        setSuggestion(data.data);
      }
    };
    
    ws.current.onclose = () => {
      console.log('Disconnected from WebSocket');
      setIsConnected(false);
    };
    
    // Clean up on unmount
    return () => {
      if (ws.current) {
        ws.current.close();
      }
    };
  }, [sessionId]);

  // Set up screen capture interval
  useEffect(() => {
    if (!captureActive || !isConnected) return;
    
    const captureTimer = setInterval(() => {
      // In a real implementation, this would capture the screen
      // and send the image to the server for analysis
      // For now, we'll simulate with a mock game state update
      
      sendMockUpdate();
    }, captureInterval);
    
    return () => {
      clearInterval(captureTimer);
    };
  }, [captureActive, isConnected, captureInterval]);

  // Function to send a mock update (simulating screen capture)
  const sendMockUpdate = () => {
    if (!ws.current || ws.current.readyState !== WebSocket.OPEN) return;
    
    // Send a mock game state update
    ws.current.send(JSON.stringify({
      type: 'game_state_update',
      player_name: playerName,
      data: {
        community_cards: ['Ah', 'Kh', '2d'],
        player_cards: {
          [playerName]: ['Jc', 'Jd']
        },
        actions: [
          {
            player: 'Player1',
            action_type: 'bet',
            amount: 100,
            street: 'flop'
          }
        ]
      }
    }));
  };

  // Start/stop screen capture
  const toggleCapture = () => {
    setCaptureActive(!captureActive);
  };

  // Handle player name change
  const handlePlayerNameChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    setPlayerName(e.target.value);
  };

  // UI rendering
  return (
    <div className="min-h-screen bg-gray-100 p-4">
      <header className="mb-6">
        <h1 className="text-3xl font-bold text-center text-blue-800">Pokerit</h1>
        <p className="text-center text-gray-600">AI-powered poker analysis tool</p>
      </header>
      
      <div className="max-w-6xl mx-auto">
        {/* Connection status */}
        <div className="mb-4 p-2 bg-white rounded shadow">
          <p className="text-sm">
            Status: 
            <span className={isConnected ? "text-green-600" : "text-red-600"}>
              {isConnected ? " Connected" : " Disconnected"}
            </span>
          </p>
          <p className="text-sm">Session ID: {sessionId}</p>
        </div>
        
        {/* Player settings */}
        <div className="mb-4 p-4 bg-white rounded shadow">
          <h2 className="text-xl font-semibold mb-2">Player Settings</h2>
          <div className="flex items-center gap-4">
            <label className="w-24">Your Name:</label>
            <input
              type="text"
              value={playerName}
              onChange={handlePlayerNameChange}
              className="border rounded px-2 py-1 flex-grow"
              placeholder="Enter your player name"
            />
          </div>
          
          <div className="mt-4 flex justify-between">
            <button
              onClick={toggleCapture}
              className={`px-4 py-2 rounded ${
                captureActive 
                  ? "bg-red-600 text-white" 
                  : "bg-green-600 text-white"
              }`}
            >
              {captureActive ? "Stop Analysis" : "Start Analysis"}
            </button>
          </div>
        </div>
        
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Game state info */}
          <div className="bg-white p-4 rounded shadow">
            <h2 className="text-xl font-semibold mb-4">Game State</h2>
            
            {gameState ? (
              <div>
                <p className="mb-2">
                  <span className="font-semibold">Street:</span> {gameState.street}
                </p>
                <p className="mb-2">
                  <span className="font-semibold">Pot:</span> ${gameState.pot}
                </p>
                <p className="mb-2">
                  <span className="font-semibold">Current Bet:</span> ${gameState.current_bet}
                </p>
                
                <div className="mb-4">
                  <h3 className="font-semibold mb-1">Community Cards:</h3>
                  <div className="flex gap-2">
                    {gameState.community_cards.length > 0 ? (
                      gameState.community_cards.map((card, i) => (
                        <div key={i} className="w-12 h-16 bg-gray-200 rounded flex items-center justify-center text-lg">
                          {card}
                        </div>
                      ))
                    ) : (
                      <p className="text-gray-500">No cards dealt</p>
                    )}
                  </div>
                </div>
                
                <div>
                  <h3 className="font-semibold mb-1">Players:</h3>
                  <ul className="divide-y">
                    {gameState.players.map((player, i) => (
                      <li key={i} className="py-2">
                        <div className="flex justify-between">
                          <span>
                            {player.name} 
                            {player.name === playerName && " (You)"}
                          </span>
                          <span>${player.stack}</span>
                        </div>
                        {player.name === playerName && player.cards.length > 0 && (
                          <div className="flex gap-2 mt-1">
                            {player.cards.map((card, j) => (
                              <div key={j} className="w-8 h-12 bg-gray-200 rounded flex items-center justify-center text-sm">
                                {card}
                              </div>
                            ))}
                          </div>
                        )}
                      </li>
                    ))}
                  </ul>
                </div>
                
                {gameState.last_action && (
                  <div className="mt-4 pt-4 border-t">
                    <h3 className="font-semibold mb-1">Last Action:</h3>
                    <p>
                      {gameState.last_action.player} {gameState.last_action.action} 
                      {gameState.last_action.amount && ` $${gameState.last_action.amount}`}
                    </p>
                  </div>
                )}
              </div>
            ) : (
              <p className="text-gray-500">Waiting for game data...</p>
            )}
          </div>
          
          {/* AI suggestion */}
          <div className="bg-white p-4 rounded shadow">
            <h2 className="text-xl font-semibold mb-4">AI Suggestion</h2>
            
            {suggestion ? (
              <div>
                <div className="mb-4 p-3 bg-blue-50 rounded border border-blue-200">
                  <p className="font-semibold text-lg">
                    Suggested Action: 
                    <span className="text-blue-700 ml-2">
                      {suggestion.action.toUpperCase()}
                      {suggestion.amount ? ` $${suggestion.amount}` : ''}
                    </span>
                  </p>
                  <div className="w-full bg-gray-200 rounded-full h-2.5 mt-2">
                    <div 
                      className="bg-blue-600 h-2.5 rounded-full" 
                      style={{ width: `${suggestion.confidence * 100}%` }}
                    ></div>
                  </div>
                  <p className="text-right text-sm text-gray-600">
                    {Math.round(suggestion.confidence * 100)}% Confidence
                  </p>
                </div>
                
                <div>
                  <h3 className="font-semibold mb-2">Reasoning:</h3>
                  <p className="text-gray-700 whitespace-pre-line">
                    {suggestion.reasoning}
                  </p>
                </div>
              </div>
            ) : (
              <p className="text-gray-500">No suggestions available yet...</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default App; 