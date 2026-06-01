"""Configuração central — lida de variáveis de ambiente.

Por padrão só dados reais (Ploomes). Modo demonstração só com
CORTEX_USE_MOCK=1 no .env (desenvolvimento).
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

from paths import data_dir

load_dotenv(data_dir() / ".env")


@dataclass(frozen=True)
class Settings:
    # ---- Ploomes (CRM) ----
    ploomes_api_key: str = os.getenv("PLOOMES_API_KEY", "")
    ploomes_base_url: str = os.getenv("PLOOMES_BASE_URL", "https://api2.ploomes.com")
    # Limite documentado da API do Ploomes: 120 req/min somando todos os usuários de integração.
    ploomes_rate_limit_per_min: int = int(os.getenv("PLOOMES_RATE_LIMIT", "120"))
    ploomes_cache_ttl: int = int(os.getenv("PLOOMES_CACHE_TTL", "300"))  # segundos

    # ---- Neppo (WhatsApp) — OAuth2 password grant ----
    neppo_client_key: str = os.getenv("NEPPO_CLIENT_KEY", "")
    neppo_client_secret: str = os.getenv("NEPPO_CLIENT_SECRET", "")
    neppo_username: str = os.getenv("NEPPO_USERNAME", "")
    neppo_password: str = os.getenv("NEPPO_PASSWORD", "")
    neppo_auth_url: str = os.getenv(
        "NEPPO_AUTH_URL", "https://api-auth.neppo.com.br/oauth2/token",
    )
    neppo_base_url: str = os.getenv("NEPPO_BASE_URL", "https://api.neppo.com.br")
    neppo_group_name: str = os.getenv("NEPPO_GROUP_NAME", "Atendimento")
    neppo_group_conf_id: int = int(os.getenv("NEPPO_GROUP_CONF_ID", "1"))
    neppo_user_id: int = int(os.getenv("NEPPO_USER_ID", "0"))

    # ---- OpenRouter (copiloto de IA — modelos :free disponíveis) ----
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_base_url: str = os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1",
    )
    openrouter_model: str = os.getenv("CORTEX_AI_MODEL", "openrouter/free")

    # chave usada para validar que o webhook veio mesmo do provedor
    webhook_validation_key: str = os.getenv("WEBHOOK_VALIDATION_KEY", "troque-esta-chave")

    # origens permitidas no CORS (separadas por vírgula); vazio = só localhost
    cors_origins_raw: str = os.getenv("CORS_ORIGINS", "")
    # cookies Secure (use 1 quando servir por HTTPS)
    secure_cookies: bool = os.getenv("SECURE_COOKIES", "") == "1"

    @property
    def cors_origins(self) -> list[str]:
        if self.cors_origins_raw.strip():
            return [o.strip() for o in self.cors_origins_raw.split(",") if o.strip()]
        return ["http://localhost:8000", "http://127.0.0.1:8000"]

    @property
    def webhook_protected(self) -> bool:
        """True quando há uma chave de webhook configurada (não a padrão)."""
        return bool(self.webhook_validation_key
                    and self.webhook_validation_key != "troque-esta-chave")

    @property
    def mock(self) -> bool:
        """Demonstração com dados fictícios — só se CORTEX_USE_MOCK=1."""
        return os.getenv("CORTEX_USE_MOCK", "").strip().lower() in ("1", "true", "yes")

    @property
    def ploomes_configured(self) -> bool:
        return bool((self.ploomes_api_key or "").strip())

    @property
    def neppo_enabled(self) -> bool:
        return bool(
            self.neppo_client_key
            and self.neppo_client_secret
            and self.neppo_username
            and self.neppo_password
        )


settings = Settings()
