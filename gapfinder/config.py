import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    mode: str
    data_dir: Path
    database_url: str
    groq_key: str
    groq_model: str
    embedding_backend: str
    embedding_model: str
    qdrant_url: str
    qdrant_key: str
    cookie_secure: bool
    demo_email: str
    demo_password: str

    @classmethod
    def from_env(cls):
        load_dotenv()
        mode = os.getenv("APP_MODE", "demo")
        if mode not in {"demo", "live"}:
            raise ValueError("APP_MODE must be demo or live")
        backend = os.getenv("EMBEDDING_BACKEND") or ("fastembed" if mode == "live" else "hash")
        if backend not in {"hash", "fastembed"}:
            raise ValueError("EMBEDDING_BACKEND must be hash or fastembed")
        if mode == "live" and not os.getenv("GROQ_API_KEY"):
            raise ValueError("Live mode requires GROQ_API_KEY")
        if mode == "live" and backend != "fastembed":
            raise ValueError("Live mode requires fastembed semantic embeddings")
        directory = Path(os.getenv("DATA_DIR", "./data"))
        return cls(mode, directory, os.getenv("DATABASE_URL", f"sqlite:///{directory}/gapfinder.db"),
                   os.getenv("GROQ_API_KEY", ""), os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                   backend, os.getenv("EMBEDDING_MODEL", "BAAI/bge-small-en-v1.5"),
                   os.getenv("QDRANT_URL", ""), os.getenv("QDRANT_API_KEY", ""),
                   os.getenv("COOKIE_SECURE", "false").lower() == "true",
                   os.getenv("DEMO_EMAIL", "demo@gapfinder.local"),
                   os.getenv("DEMO_PASSWORD", "study-better-2026"))
