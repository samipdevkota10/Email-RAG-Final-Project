#!/bin/bash

# Navigate to project root
cd "$(dirname "$0")"

# Activate virtual environment (if not already activated)
if [ -z "$VIRTUAL_ENV" ]; then
    source bin/activate
fi

# Run the FastAPI server
uvicorn src.app:app --reload --host 0.0.0.0 --port 8000

