# Pokerit

An AI-powered poker analysis tool that provides real-time suggestions and records gameplay for learning purposes.

## Features

- Screen capture and computer vision for card and action recognition
- Real-time game state tracking
- AI-powered strategy suggestions using Claude
- Hand history recording and analysis
- Simple GUI for displaying game information and AI suggestions

## Project Structure

```
pokerit/
├── src/
│   ├── vision/           # Screen capture and computer vision
│   │   ├── capture.py    # Screen capture module
│   │   └── recognition.py # Card and action recognition
│   ├── game/            # Game state tracking
│   │   ├── state.py     # Game state management
│   │   └── rules.py     # Poker rules and hand evaluation
│   ├── ai/              # AI strategy engine
│   │   ├── engine.py    # Main AI engine
│   │   └── prompts.py   # LLM prompts
│   ├── database/        # Database management
│   │   ├── models.py    # Database models
│   │   └── manager.py   # Database operations
│   └── gui/             # GUI components
│       ├── main.py      # Main application window
│       └── widgets.py   # Custom widgets
├── tests/               # Test files
├── config/             # Configuration files
└── data/               # Data storage
    └── database/       # SQLite database
```

## Setup

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

4. Run the application:
```bash
python src/gui/main.py
```

## Development

- Use `black` for code formatting
- Use `flake8` for linting
- Use `mypy` for type checking
- Run tests with `pytest`

## License

This project is licensed under the MIT License - see the LICENSE file for details. 