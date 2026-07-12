# Jupyter Notebook Setup Guide

This project is configured to use Jupyter notebooks for interactive development and analysis. You have two options for running Jupyter:

## Option 1: Local Jupyter (Recommended for Development)

### Prerequisites
- Python 3.11+ virtual environment with dev dependencies installed
- Run: `uv sync --extra dev`

### Start Jupyter Lab Locally

```bash
# Activate the project environment
source .venv/bin/activate

# Start Jupyter Lab
jupyter lab
```

The Jupyter server will start at `http://localhost:8888` and automatically open in your browser.

**Kernel**: The "Poker Trainer (Python 3.11)" kernel is already registered and will have access to:
- All project dependencies
- Your local Python environment
- Database connections via DATABASE_URL from .env
- Project source code in `src/`

### Create a New Notebook

In Jupyter Lab:
1. Click **File** → **New** → **Notebook**
2. Select **Poker Trainer (Python 3.11)** kernel
3. Start coding!

## Option 2: Docker-based Jupyter

### Start Jupyter in Docker Container

```bash
# Start Jupyter service alongside other services
docker compose --profile jupyter up -d

# Or rebuild and start fresh
docker compose --profile jupyter up -d --build
```

Access Jupyter Lab at `http://localhost:8888`

### Important Notes for Docker Jupyter
- The container has access to the PostgreSQL database
- Source code is mounted at `/app/src` for live editing
- Notebooks should be saved in the `./notebooks/` directory (mounted at `/app/notebooks`)
- To stop: `docker compose --profile jupyter down`

## Example Notebook Usage

```python
# Import project modules
from poker_engine.engine import PokerEngine
from src.ai_functions.coach_engine import ConversationEngine
import pandas as pd

# Connect to database
import os
from sqlalchemy import create_engine
db_url = os.getenv('DATABASE_URL')
db = create_engine(db_url)

# Query data
import sqlalchemy as sa
with db.connect() as conn:
    result = conn.execute(sa.text("SELECT * FROM games LIMIT 5"))
    for row in result:
        print(row)
```

## Troubleshooting

### Kernel not found
```bash
# Re-register the kernel
python -m ipykernel install --user --name poker-trainer --display-name "Poker Trainer (Python 3.11)" --force
```

### Import errors in notebook
- Ensure the kernel is using the correct environment
- Check: `import sys; print(sys.executable)` in a notebook cell
- Verify dev dependencies are installed: `uv sync --extra dev`

### Docker Jupyter connection issues
- Check database is running: `docker compose ps`
- Verify .env file is present with DATABASE_URL set
- Check logs: `docker compose logs jupyter`

## Configuration

### Jupyter Configuration Files
- Kernel spec: `~/.local/share/jupyter/kernels/poker-trainer/`
- Jupyter config: `~/.jupyter/jupyter_config.py`

### Customizing Jupyter Lab Settings
Create `.jupyter/jupyter_lab_config.py`:

```python
# Example: Set default notebook format
c.NotebookApp.notebook_dir = '/path/to/notebooks'
c.NotebookApp.allow_remote_access = True
c.NotebookApp.allow_origin = '*'
```
