# ferelix-server

A FastAPI application for managing media content, built with [uv](https://github.com/astral-sh/uv) package manager.

## Requirements

- Python >= 3.11
- [uv](https://github.com/astral-sh/uv) package manager

## Installation

1. Install dependencies:
```bash
uv sync
```

## Running the Application

Start the development server:
```bash
uv run uvicorn app.main:app --reload
```

The API will be available at `http://localhost:8000`

## API Documentation

Once the server is running, you can access:
- Interactive API docs: `http://localhost:8000/docs`
- OpenAPI schema: `http://localhost:8000/openapi.json`

## Endpoints

### GET /movies

Returns a list of movies.

**Response:**
```json
[
  {
    "id": "1",
    "title": "Big Buck Bunny",
    "description": "A large and lovable rabbit deals with three tiny bullies, led by a flying squirrel, who are determined to squelch his happiness.",
    "posterUrl": "https://peach.blender.org/wp-content/uploads/title_anouncement.jpg?x11217",
    "backdropUrl": "https://peach.blender.org/wp-content/uploads/title_anouncement.jpg?x11217",
    "hlsUrl": "https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
    "duration": 600,
    "year": 2008,
    "genre": "Animation"
  }
]
```

## Development

### Linting

Run ruff to check code quality:
```bash
uv run ruff check .
```

### Formatting

Format code with ruff:
```bash
uv run ruff format .
```
