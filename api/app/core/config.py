from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, List


class Settings(BaseSettings):
	model_config = SettingsConfigDict(
		extra="ignore"
	)
	# CORS
	origin_regex: str = Field(default=".*", alias="ALLOWED_ORIGIN_REGEX")
	allow_credentials: bool = Field(default=False, alias="ALLOW_CREDENTIALS")
	allow_methods: List[str] = Field(default_factory=lambda: ["*"], alias="ALLOW_METHODS")
	allow_headers: List[str] = Field(default_factory=lambda: ["*"], alias="ALLOW_HEADERS")

	# Redis
	redis_url: str = Field(..., alias="REDIS_URL")
	redis_pool_max_connections: int = Field(default=20, alias="REDIS_POOL_MAX_CONNECTIONS")

	# Redis task manager
	task_queue_prefix: str = Field(default="bridge:tasks", alias="TASK_QUEUE_PREFIX")
	task_default_max_attempts: int = Field(default=5, alias="TASK_DEFAULT_MAX_ATTEMPTS")
	task_default_lease_seconds: int = Field(default=300, alias="TASK_DEFAULT_LEASE_SECONDS")
	task_retry_base_seconds: int = Field(default=30, alias="TASK_RETRY_BASE_SECONDS")
	task_retry_max_seconds: int = Field(default=1800, alias="TASK_RETRY_MAX_SECONDS")
	task_idempotency_ttl_seconds: int = Field(default=604800, alias="TASK_IDEMPOTENCY_TTL_SECONDS")

	# API auth
	api_token: str = Field(..., alias="API_TOKEN")

	# Postgres
	postgres_host: str = Field(..., alias="POSTGRES_HOST")
	postgres_port: int = Field(5432, alias="POSTGRES_PORT")
	postgres_user: str = Field(..., alias="POSTGRES_USER")
	postgres_password: Optional[str] = Field(None, alias="POSTGRES_PASSWORD")
	postgres_db: str = Field(..., alias="POSTGRES_DB")

	# GoogleSheets
	sheet_id: str = Field(..., alias="SHEET_ID")
	service_account_file: str = Field(..., alias="SERVICE_ACCOUNT_FILE")
	sheet_scopes: Optional[List[str]] = Field(default=None, alias="SHEET_SCOPES")

	# Logging
	log_level: str = Field(default="INFO", alias="LOG_LEVEL")
	to_file: bool = Field(default=False, alias="LOG_TO_FILE")
	to_console: bool = Field(default=True, alias="LOG_TO_CONSOLE") 


settings = Settings()
