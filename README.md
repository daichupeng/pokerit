# Pokerit

An AI-powered poker analysis tool that provides real-time suggestions and records gameplay for learning purposes.

## Features

- Browser extension for screen capture and poker game recognition
- Real-time game state tracking
- AI-powered strategy suggestions using Claude
- Hand history recording and analysis
- Web interface for displaying game information and AI suggestions

## Architecture

Pokerit is structured as a web application with these main components:

1. **Backend (FastAPI)** - Handles game state tracking, AI suggestions, and database operations
2. **Frontend (React)** - Provides the user interface for viewing game state and AI suggestions
3. **Browser Extension (Chrome)** - Captures the poker game screen and sends it to the backend

### Backend Components

- **Vision Module** - Analyzes captured images to recognize cards and actions
- **Game State Module** - Tracks the game state based on recognized elements
- **AI Strategy Module** - Generates strategic suggestions using Claude
- **Database Module** - Stores hand histories and player statistics

### Frontend Components

- **Game State View** - Displays current cards, pot, player stacks, etc.
- **AI Suggestion Panel** - Shows recommended actions with reasoning
- **History View** - Displays past hands and decisions

### Browser Extension

- **Screen Capture** - Captures the poker client screen
- **WebSocket Communication** - Sends images to the backend
- **Session Management** - Maintains connection with the backend

## Project Structure

```
pokerit/
├── src/                # Backend code
│   ├── vision/         # Screen capture and computer vision
│   ├── game/           # Game state tracking
│   ├── ai/             # AI strategy engine
│   ├── database/       # Database management
│   └── main.py         # FastAPI application
├── frontend/           # React frontend
│   ├── src/            # React components
│   ├── public/         # Static assets
│   └── package.json    # Frontend dependencies
├── extension/          # Chrome extension
│   ├── manifest.json   # Extension manifest
│   ├── popup.html      # Extension popup
│   ├── content.js      # Content script
│   └── background.js   # Background script
├── tests/              # Test files
├── data/               # Data storage
│   └── database/       # SQLite database
├── Dockerfile          # Backend Docker config
├── docker-compose.yml  # Docker Compose config
└── requirements.txt    # Backend dependencies
```

## Setup

### Backend

1. Create a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables:
```bash
cp .env.example .env
# Edit .env with your Claude API key and other settings
```

4. Run the backend:
```bash
uvicorn src.main:app --reload
```

### Frontend

1. Install dependencies:
```bash
cd frontend
npm install
```

2. Run the development server:
```bash
npm run dev
```

### Browser Extension

1. Build the extension:
```bash
cd extension
# No build step required for basic extension
```

2. Load the extension in Chrome:
   - Go to chrome://extensions/
   - Enable "Developer mode"
   - Click "Load unpacked" and select the `extension` directory

## Docker Deployment

Run the entire application using Docker Compose:

```bash
docker-compose up -d
```

This will start both the backend and frontend services.

## Development

- Backend API is available at http://localhost:8000
- Frontend is available at http://localhost:3000
- API documentation is available at http://localhost:8000/docs

## License

This project is licensed under the MIT License - see the LICENSE file for details. 