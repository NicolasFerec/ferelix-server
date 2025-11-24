from fastapi import FastAPI

from app.models import Movie

app = FastAPI(title="Ferelix Server", version="0.1.0")


@app.get("/movies", response_model=list[Movie])
async def get_movies() -> list[Movie]:
    """Get a list of movies."""
    movies = [
        Movie(
            id="1",
            title="Big Buck Bunny",
            description="A large and lovable rabbit deals with three tiny bullies, led by a flying squirrel, who are determined to squelch his happiness.",
            posterUrl="https://peach.blender.org/wp-content/uploads/title_anouncement.jpg?x11217",
            backdropUrl="https://peach.blender.org/wp-content/uploads/title_anouncement.jpg?x11217",
            hlsUrl="https://test-streams.mux.dev/x36xhzz/x36xhzz.m3u8",
            duration=600,
            year=2008,
            genre="Animation",
        ),
    ]
    return movies

