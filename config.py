import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass
class Config:
    telegram_bot_token: str
    groq_api_key: str
    gemini_api_key: str
    openai_api_key: str
    gmail_address: str
    gmail_app_password: str
    my_telegram_user_id: int
    serper_api_key: str
    tavily_api_key: str
    my_name: str
    company_name: str
    my_role: str
    my_one_liner: str
    # Autonomy / agent
    auto_approve: bool
    heartbeat_hours: int
    autonomy_level: str          # cautious | balanced | autonomous
    voice_replies: bool          # speak responses back to voice messages
    daily_llm_call_cap: int      # 0 = unlimited
    agent_paused: bool           # kill switch

    # Local model (Ollama) + caching
    ollama_enabled: bool
    ollama_base_url: str
    ollama_model: str
    semantic_cache: bool
    cache_distance_threshold: float
    # Google Calendar (optional)
    google_credentials_path: str
    google_token_path: str
    # X / Twitter (optional)
    x_api_key: str
    x_api_secret: str
    x_access_token: str
    x_access_token_secret: str
    x_bearer_token: str

def load_config() -> Config:
    missing = []
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        missing.append("TELEGRAM_BOT_TOKEN")
    if not os.getenv("MY_TELEGRAM_USER_ID"):
        missing.append("MY_TELEGRAM_USER_ID")

    # At least one LLM provider key is required. Any one is enough — the router
    # falls back across whatever is configured (Groq -> Gemini -> OpenAI).
    llm_keys = [
        os.getenv("GROQ_API_KEY"),
        os.getenv("GOOGLE_GEMINI_API_KEY"),
        os.getenv("OPENAI_API_KEY"),
    ]
    if not any(llm_keys):
        missing.append("at least one of GROQ_API_KEY / GOOGLE_GEMINI_API_KEY / OPENAI_API_KEY")

    if missing:
        print(f"[FATAL] Missing required env vars: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in the required values.")
        exit(1)

    return Config(
        telegram_bot_token=os.getenv("TELEGRAM_BOT_TOKEN"),
        groq_api_key=os.getenv("GROQ_API_KEY", ""),
        gemini_api_key=os.getenv("GOOGLE_GEMINI_API_KEY", ""),
        openai_api_key=os.getenv("OPENAI_API_KEY", ""),
        gmail_address=os.getenv("GMAIL_ADDRESS", ""),
        gmail_app_password=os.getenv("GMAIL_APP_PASSWORD", ""),
        my_telegram_user_id=int(os.getenv("MY_TELEGRAM_USER_ID", "0")),
        serper_api_key=os.getenv("SERPER_API_KEY", ""),
        tavily_api_key=os.getenv("TAVILY_API_KEY", ""),
        my_name=os.getenv("MY_NAME", "Founder"),
        company_name=os.getenv("MY_COMPANY_NAME", "My Company"),
        my_role=os.getenv("MY_ROLE", "Founder"),
        my_one_liner=os.getenv("MY_ONE_LINER", ""),
        auto_approve=os.getenv("AUTO_APPROVE", "false").strip().lower() in ("1", "true", "yes", "on"),
        heartbeat_hours=int(os.getenv("HEARTBEAT_HOURS", "4") or "4"),
        autonomy_level=os.getenv("AUTONOMY_LEVEL", "balanced").strip().lower(),
        voice_replies=os.getenv("VOICE_REPLIES", "true").strip().lower() in ("1", "true", "yes", "on"),
        daily_llm_call_cap=int(os.getenv("DAILY_LLM_CALL_CAP", "0") or "0"),
        agent_paused=os.getenv("AGENT_PAUSED", "false").strip().lower() in ("1", "true", "yes", "on"),
        ollama_enabled=os.getenv("OLLAMA_ENABLED", "false").strip().lower() in ("1", "true", "yes", "on"),
        ollama_base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1").strip(),
        ollama_model=os.getenv("OLLAMA_MODEL", "llama3.1").strip(),
        semantic_cache=os.getenv("SEMANTIC_CACHE", "true").strip().lower() in ("1", "true", "yes", "on"),
        cache_distance_threshold=float(os.getenv("CACHE_DISTANCE_THRESHOLD", "0.08") or "0.08"),
        google_credentials_path=os.getenv("GOOGLE_CREDENTIALS_PATH", "./data/google_credentials.json"),
        google_token_path=os.getenv("GOOGLE_TOKEN_PATH", "./data/google_token.json"),
        x_api_key=os.getenv("X_API_KEY", ""),
        x_api_secret=os.getenv("X_API_SECRET", ""),
        x_access_token=os.getenv("X_ACCESS_TOKEN", ""),
        x_access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET", ""),
        x_bearer_token=os.getenv("X_BEARER_TOKEN", ""),
    )

config = load_config()
