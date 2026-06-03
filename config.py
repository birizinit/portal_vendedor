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

    # ---- Alertas proativos ----
    # minutos aguardando resposta do cliente até virar alerta de SLA
    sla_first_reply_minutes: int = int(os.getenv("CORTEX_SLA_MINUTES", "15"))
    # dias sem compra / ciclo habitual >= este fator => alerta de reativação
    reactivation_factor: float = float(os.getenv("CORTEX_REACTIVATION_FACTOR", "1.3"))
    # dias parado no mesmo estágio do funil até virar alerta
    stale_deal_days: int = int(os.getenv("CORTEX_STALE_DEAL_DAYS", "7"))

    # ---- Funil de entrada (leads de WhatsApp viram negócio aqui) ----
    intake_pipeline_name: str = os.getenv("CORTEX_INTAKE_PIPELINE", "Entradas e Prospecção")
    # estágio inicial; vazio = primeiro estágio (menor Ordination) do funil
    intake_stage_name: str = os.getenv("CORTEX_INTAKE_STAGE", "")
    # "motivo"/origem registrado no negócio criado a partir do WhatsApp
    intake_source: str = os.getenv("CORTEX_INTAKE_SOURCE", "WhatsApp (Neppo)")

    # ---- OpenRouter (copiloto de IA — modelos :free disponíveis) ----
    openrouter_api_key: str = os.getenv("OPENROUTER_API_KEY", "")
    openrouter_base_url: str = os.getenv(
        "OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1",
    )
    openrouter_model: str = os.getenv("CORTEX_AI_MODEL", "openrouter/free")

    # chave usada para validar que o webhook veio mesmo do provedor
    webhook_validation_key: str = os.getenv("WEBHOOK_VALIDATION_KEY", "troque-esta-chave")
    # libera webhook sem chave (SÓ para desenvolvimento local) — em produção
    # deixe 0 e configure WEBHOOK_VALIDATION_KEY
    webhook_allow_insecure_raw: str = os.getenv("WEBHOOK_ALLOW_INSECURE", "")

    # origens permitidas no CORS (separadas por vírgula); vazio = só localhost
    cors_origins_raw: str = os.getenv("CORS_ORIGINS", "")
    # cookies Secure (use 1 quando servir por HTTPS)
    secure_cookies: bool = os.getenv("SECURE_COOKIES", "") == "1"

    # ---- Assistente noturno (piloto) ----
    night_agent_enabled: bool = os.getenv("CORTEX_NIGHT_AGENT", "") == "1"
    night_tz: str = os.getenv("CORTEX_NIGHT_TZ", "America/Sao_Paulo")
    night_start: str = os.getenv("CORTEX_NIGHT_START", "18:10")
    night_end: str = os.getenv("CORTEX_NIGHT_END", "07:00")
    night_max_replies: int = int(os.getenv("CORTEX_NIGHT_MAX_REPLIES", "5"))
    night_cooldown_sec: int = int(os.getenv("CORTEX_NIGHT_COOLDOWN_SEC", "120"))

    # ---- Carteira (sync + campanhas WhatsApp) ----
    portfolio_sync_page_size: int = int(os.getenv("CORTEX_PORTFOLIO_PAGE_SIZE", "100"))
    portfolio_sync_max_pages: int = int(os.getenv("CORTEX_PORTFOLIO_MAX_PAGES", "80"))
    portfolio_campaign_delay_sec: float = float(
        os.getenv("CORTEX_PORTFOLIO_CAMPAIGN_DELAY", "60"),
    )
    portfolio_campaign_max_per_day: int = int(
        os.getenv("CORTEX_PORTFOLIO_CAMPAIGN_MAX_DAY", "80"),
    )
    portfolio_campaign_hour_start: int = int(
        os.getenv("CORTEX_PORTFOLIO_HOUR_START", "8"),
    )
    portfolio_campaign_hour_end: int = int(
        os.getenv("CORTEX_PORTFOLIO_HOUR_END", "18"),
    )

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
    def webhook_allow_insecure(self) -> bool:
        """Permite webhook sem chave (apenas dev). Produção deve ficar False."""
        return self.webhook_allow_insecure_raw.strip().lower() in ("1", "true", "yes")

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
