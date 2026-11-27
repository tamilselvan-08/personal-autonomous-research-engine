import enum


class TaskStatus(enum.StrEnum):
    DRAFT = "draft"
    PLANNING = "planning"
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ProviderType(enum.StrEnum):
    OPENAI = "openai"
    GEMINI = "gemini"
    ANTHROPIC = "anthropic"
    XAI = "xai"
    DEEPSEEK = "deepseek"
    MISTRAL = "mistral"
    OPENAI_COMPATIBLE = "openai_compatible"


class HealthState(enum.StrEnum):
    UNKNOWN = "unknown"
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    INVALID_CREDENTIALS = "invalid_credentials"
    QUOTA_EXHAUSTED = "quota_exhausted"
    MISCONFIGURED = "misconfigured"


class ModelRole(enum.StrEnum):
    """Who is asking for a completion. 'default' applies when a role has no route."""

    DEFAULT = "default"
    PLANNER = "planner"
    RESEARCHER = "researcher"
    EXTRACTOR = "extractor"
    VERIFIER = "verifier"
    SUMMARIZER = "summarizer"


class ModelCapability(enum.StrEnum):
    """What a model can do. 'json' mirrors ai_models.supports_json (the router uses it)."""

    JSON = "json"
    VISION = "vision"
    TOOLS = "tools"
    REASONING = "reasoning"


class UsageOutcome(enum.StrEnum):
    SUCCESS = "success"
    RETRY = "retry"  # this attempt failed; the same model was tried again
    FALLBACK = "fallback"  # this attempt failed; the next model in the chain was tried
    ERROR = "error"  # this attempt failed and nothing further was tried


class UsagePurpose(enum.StrEnum):
    COMPLETION = "completion"
    CONNECTION_TEST = "connection_test"
    ROUTING_TEST = "routing_test"


class SecretKind(enum.StrEnum):
    LLM_API_KEY = "llm_api_key"
