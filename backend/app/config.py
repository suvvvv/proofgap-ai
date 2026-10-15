import os
from dataclasses import dataclass, field
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _bool(name: str, default: bool) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    # STORE=firestore (deployed, Firebase/GCP) or sql (SQLite locally / Postgres via DATABASE_URL).
    store: str = field(default_factory=lambda: os.getenv("STORE", "sql").strip().lower())
    gcp_project: str | None = field(default_factory=lambda: os.getenv("GOOGLE_CLOUD_PROJECT"))
    firestore_database: str = field(default_factory=lambda: os.getenv("FIRESTORE_DATABASE", "(default)"))
    database_url: str = field(default_factory=lambda: os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR.parent / 'proofgap.db'}"))
    scenario_path: Path = field(default_factory=lambda: Path(os.getenv("SCENARIO_PATH", BASE_DIR / "seed" / "m04_vibration.json")))
    # Gemini: set GEMINI_API_KEY (Google AI Studio) or GOOGLE_GENAI_USE_VERTEXAI=true + project/location.
    gemini_api_key: str | None = field(default_factory=lambda: os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))
    use_vertex: bool = field(default_factory=lambda: _bool("GOOGLE_GENAI_USE_VERTEXAI", False))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-3.5-flash"))
    gemini_fallback_models: list = field(default_factory=lambda: [m.strip() for m in os.getenv(
        "GEMINI_FALLBACK_MODELS", "gemini-flash-latest,gemini-3.5-flash-lite").split(",") if m.strip()])
    gemini_thinking_level: str = field(default_factory=lambda: os.getenv("GEMINI_THINKING_LEVEL", "LOW"))
    gemini_timeout_s: float = field(default_factory=lambda: float(os.getenv("GEMINI_TIMEOUT_S", "25")))  # per request
    gemini_total_timeout_s: float = field(default_factory=lambda: float(os.getenv("GEMINI_TOTAL_TIMEOUT_S", "45")))
    allow_demo_reset: bool = field(default_factory=lambda: _bool("ALLOW_DEMO_RESET", True))
    static_dir: Path = field(default_factory=lambda: Path(os.getenv("STATIC_DIR", BASE_DIR.parent.parent / "frontend" / "dist")))


settings = Settings()
