from pydantic import BaseModel


class Movie(BaseModel):
    id: str
    title: str
    description: str
    posterUrl: str
    backdropUrl: str
    hlsUrl: str
    duration: int
    year: int
    genre: str

