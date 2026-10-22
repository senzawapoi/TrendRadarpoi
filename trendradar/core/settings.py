"""Unified YAML and environment settings for all TrendRadar runtime surfaces."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any

import yaml

DEFAULT_CONFIG_PATH = Path("config/config.yaml")

DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
DEFAULT_GEMINI_TIMEOUT_SECONDS = 30.0
DEFAULT_GEMINI_MAX_ATTEMPTS = 3
DEFAULT_GEMINI_RETRY_BACKOFF_SECONDS = 1.0
DEFAULT_GEMINI_MIN_REQUEST_INTERVAL_SECONDS = 1.0
DEFAULT_GEMINI_MAX_INPUT_CHARS = 32_000
DEFAULT_GEMINI_MAX_OUTPUT_CHARS = 12_000


def _freeze(value: Any) -> Any:
    if isinstance(value, Mapping):
        return MappingProxyType({str(key): _freeze(item) for key, item in value.items()})
    if isinstance(value, list | tuple):
        return tuple(_freeze(item) for item in value)
    if isinstance(value, set | frozenset):
        return frozenset(_freeze(item) for item in value)
    return deepcopy(value)


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple | frozenset):
        return [_thaw(item) for item in value]
    return deepcopy(value)


def _bounded_int(value: Any, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _bounded_float(value: Any, default: float, *, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    if not math.isfinite(parsed):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _looks_sensitive(key: str) -> bool:
    normalized = str(key).strip().lower().replace("-", "_")
    return any(
        marker in normalized
        for marker in ("api_key", "apikey", "credential", "password", "secret", "token")
    )


def _discard_gemini_credentials(value: Any, *, gemini_scope: bool = False) -> Any:
    """Copy YAML while removing credential-looking values from Gemini sections."""
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            normalized = key.strip().lower().replace("-", "_")
            child_scope = gemini_scope or "gemini" in normalized
            if child_scope and (
                _looks_sensitive(normalized)
                or normalized == "key"
                or normalized.endswith("_key")
            ):
                continue
            sanitized[key] = _discard_gemini_credentials(item, gemini_scope=child_scope)
        return sanitized
    if isinstance(value, list | tuple):
        return [_discard_gemini_credentials(item, gemini_scope=gemini_scope) for item in value]
    return deepcopy(value)


def load_yaml_config(config_path: str | Path) -> dict[str, Any]:
    """Load a UTF-8 YAML mapping from ``config_path``."""
    path = Path(config_path)
    with path.open(encoding="utf-8") as config_file:
        data = yaml.safe_load(config_file)

    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise ValueError(f"配置文件根节点必须是 mapping: {path}")
    return deepcopy(dict(data))


@dataclass(frozen=True, repr=False)
class RuntimeSettings:
    """Read-only settings with explicit environment-over-YAML precedence."""

    config_path: Path
    _raw_config: Mapping[str, Any]
    _environ: Mapping[str, str]

    @property
    def raw_config(self) -> Mapping[str, Any]:
        return self._raw_config

    def as_dict(self) -> dict[str, Any]:
        """Return a mutable copy for compatibility with legacy dictionary consumers."""
        return _thaw(self._raw_config)

    def _environment_value(self, key: str) -> str | None:
        value = self._environ.get(key)
        if value is None:
            return None
        stripped = str(value).strip()
        return stripped or None

    def has_environment(self, key: str) -> bool:
        """Return whether ``key`` has a non-empty environment override."""
        return self._environment_value(key) is not None

    def _lark_environment_key(self, suffix: str) -> str:
        """Prefer LARK_* while retaining FEISHU_* as a compatibility alias."""
        lark_key = f"LARK_{suffix}"
        feishu_key = f"FEISHU_{suffix}"
        return lark_key if self.has_environment(lark_key) else feishu_key

    def _lark_yaml_path(self, name: str) -> str:
        root = "lark" if isinstance(self.yaml_value("lark"), Mapping) else "feishu"
        return f"{root}.{name}"

    def yaml_value(self, path: str | tuple[str, ...], default: Any = None) -> Any:
        """Read a dot-separated or tuple YAML path from the frozen mapping."""
        parts = tuple(path.split(".")) if isinstance(path, str) else path
        current: Any = self._raw_config
        for part in parts:
            if not isinstance(current, Mapping) or part not in current:
                return default
            current = current[part]
        return current

    def get_str(
        self,
        env_key: str,
        yaml_path: str | tuple[str, ...] | None = None,
        default: str = "",
    ) -> str:
        env_value = self._environment_value(env_key)
        if env_value is not None:
            return env_value
        yaml_value = self.yaml_value(yaml_path) if yaml_path else None
        if yaml_value is None:
            return default
        return str(yaml_value).strip() or default

    def get_int(
        self,
        env_key: str,
        yaml_path: str | tuple[str, ...] | None = None,
        default: int = 0,
    ) -> int:
        env_value = self._environment_value(env_key)
        if env_value is not None:
            try:
                return int(env_value)
            except ValueError:
                pass
        yaml_value = self.yaml_value(yaml_path) if yaml_path else None
        try:
            return int(yaml_value) if yaml_value is not None else default
        except (TypeError, ValueError, OverflowError):
            return default

    def get_float(
        self,
        env_key: str,
        yaml_path: str | tuple[str, ...] | None = None,
        default: float = 0.0,
    ) -> float:
        env_value = self._environment_value(env_key)
        if env_value is not None:
            try:
                return float(env_value)
            except ValueError:
                pass
        yaml_value = self.yaml_value(yaml_path) if yaml_path else None
        try:
            return float(yaml_value) if yaml_value is not None else default
        except (TypeError, ValueError):
            return default

    def get_bool(
        self,
        env_key: str,
        yaml_path: str | tuple[str, ...] | None = None,
        default: bool = False,
    ) -> bool:
        env_value = self._environment_value(env_key)
        if env_value is not None:
            normalized = env_value.lower()
            if normalized in {"true", "1", "yes", "on"}:
                return True
            if normalized in {"false", "0", "no", "off"}:
                return False
        yaml_value = self.yaml_value(yaml_path) if yaml_path else None
        if yaml_value is None:
            return default
        if isinstance(yaml_value, bool):
            return yaml_value
        normalized = str(yaml_value).strip().lower()
        if normalized in {"true", "1", "yes", "on"}:
            return True
        if normalized in {"false", "0", "no", "off"}:
            return False
        return default

    def get_csv(
        self,
        env_key: str,
        yaml_path: str | tuple[str, ...] | None = None,
        default: tuple[str, ...] = (),
    ) -> tuple[str, ...]:
        env_value = self._environment_value(env_key)
        if env_value is not None:
            return tuple(item.strip() for item in env_value.split(",") if item.strip())
        yaml_value = self.yaml_value(yaml_path) if yaml_path else None
        if yaml_value is None:
            return default
        if isinstance(yaml_value, str):
            return tuple(item.strip() for item in yaml_value.split(",") if item.strip())
        if isinstance(yaml_value, tuple | list):
            return tuple(str(item).strip() for item in yaml_value if str(item).strip())
        return default

    @property
    def timezone(self) -> str:
        return self.get_str("TIMEZONE", "app.timezone", "Asia/Shanghai")

    @property
    def gemini_api_key(self) -> str:
        """Read the Gemini credential from the environment only."""
        return self._environment_value("GEMINI_API_KEY") or ""

    @property
    def gemini_enabled(self) -> bool:
        return self.get_bool("GEMINI_ENABLED", "ai.gemini.enabled", True)

    @property
    def gemini_config(self) -> dict[str, Any]:
        """Return bounded, secret-free configuration accepted by ``GeminiConfig``."""
        return {
            "enabled": self.gemini_enabled,
            "model": self.get_str(
                "GEMINI_MODEL",
                "ai.gemini.model",
                DEFAULT_GEMINI_MODEL,
            ),
            "timeout_seconds": _bounded_float(
                self.get_float(
                    "GEMINI_TIMEOUT_SECONDS",
                    "ai.gemini.timeout_seconds",
                    DEFAULT_GEMINI_TIMEOUT_SECONDS,
                ),
                DEFAULT_GEMINI_TIMEOUT_SECONDS,
                minimum=1.0,
                maximum=120.0,
            ),
            "max_attempts": _bounded_int(
                self.get_int(
                    "GEMINI_MAX_ATTEMPTS",
                    "ai.gemini.max_attempts",
                    DEFAULT_GEMINI_MAX_ATTEMPTS,
                ),
                DEFAULT_GEMINI_MAX_ATTEMPTS,
                minimum=1,
                maximum=5,
            ),
            "retry_backoff_seconds": _bounded_float(
                self.get_float(
                    "GEMINI_RETRY_BACKOFF_SECONDS",
                    "ai.gemini.retry_backoff_seconds",
                    DEFAULT_GEMINI_RETRY_BACKOFF_SECONDS,
                ),
                DEFAULT_GEMINI_RETRY_BACKOFF_SECONDS,
                minimum=0.0,
                maximum=30.0,
            ),
            "min_request_interval_seconds": _bounded_float(
                self.get_float(
                    "GEMINI_MIN_REQUEST_INTERVAL_SECONDS",
                    "ai.gemini.min_request_interval_seconds",
                    DEFAULT_GEMINI_MIN_REQUEST_INTERVAL_SECONDS,
                ),
                DEFAULT_GEMINI_MIN_REQUEST_INTERVAL_SECONDS,
                minimum=0.0,
                maximum=60.0,
            ),
            "max_input_chars": _bounded_int(
                self.get_int(
                    "GEMINI_MAX_INPUT_CHARS",
                    "ai.gemini.max_input_chars",
                    DEFAULT_GEMINI_MAX_INPUT_CHARS,
                ),
                DEFAULT_GEMINI_MAX_INPUT_CHARS,
                minimum=256,
                maximum=200_000,
            ),
            "max_output_chars": _bounded_int(
                self.get_int(
                    "GEMINI_MAX_OUTPUT_CHARS",
                    "ai.gemini.max_output_chars",
                    DEFAULT_GEMINI_MAX_OUTPUT_CHARS,
                ),
                DEFAULT_GEMINI_MAX_OUTPUT_CHARS,
                minimum=256,
                maximum=50_000,
            ),
        }

    @property
    def intelligence_story_wording_enabled(self) -> bool:
        """Whether optional Story wording enhancement is enabled."""
        return self.get_bool(
            "INTELLIGENCE_STORY_WORDING_ENABLED",
            "intelligence.story.wording.enabled",
            False,
        )

    @property
    def lark_app_id(self) -> str:
        return self.get_str(self._lark_environment_key("APP_ID"))

    @property
    def lark_app_secret(self) -> str:
        return self.get_str(self._lark_environment_key("APP_SECRET"))

    @property
    def lark_allowed_users(self) -> tuple[str, ...]:
        return self.get_csv(
            self._lark_environment_key("ALLOWED_USERS"),
            self._lark_yaml_path("allowed_users"),
        )

    @property
    def lark_config(self) -> dict[str, Any]:
        """Lark transport settings; credentials never enter the loader payload."""
        identity_key = self._lark_environment_key("IDENTITY_FIELDS")
        allowed_users_key = self._lark_environment_key("ALLOWED_USERS")
        fields = self.yaml_value(self._lark_yaml_path("identity_fields"))
        if self.has_environment(identity_key):
            try:
                fields = json.loads(self.get_str(identity_key))
            except ValueError:
                fields = {}
        elif self.has_environment(allowed_users_key) or fields is None:
            fields = {"open_id": list(self.lark_allowed_users)}
        config = {
            "enabled": self.get_bool(
                self._lark_environment_key("ENABLED"), self._lark_yaml_path("enabled"), False
            ),
            "identity_fields": _thaw(fields) if isinstance(fields, Mapping) else {},
            "allowed_chat_types": self.get_csv(
                self._lark_environment_key("ALLOWED_CHAT_TYPES"),
                self._lark_yaml_path("allowed_chat_types"),
                ("p2p", "group"),
            ),
            "bot_id": self.get_str(
                self._lark_environment_key("BOT_ID"), self._lark_yaml_path("bot_id")
            ),
            "timezone": "Asia/Shanghai",
            "delivery_enabled": self.get_bool(
                self._lark_environment_key("DELIVERY_ENABLED"),
                self._lark_yaml_path("delivery.enabled"),
                False,
            ),
            "delivery_target": self.get_str(
                self._lark_environment_key("DELIVERY_TARGET"),
                self._lark_yaml_path("delivery.target"),
            ),
            "delivery_time": self.get_str(
                self._lark_environment_key("DELIVERY_TIME"),
                self._lark_yaml_path("delivery.time"),
                self.get_str("PUSH_WINDOW_START", "notification.push_window.start", "00:00"),
            ),
            "delivery_end": self.get_str(
                self._lark_environment_key("DELIVERY_END"),
                self._lark_yaml_path("delivery.end"),
                self.get_str("PUSH_WINDOW_END", "notification.push_window.end", "23:59"),
            ),
        }
        for name, default, minimum, maximum in (
            ("reconnect_attempts", 5, 1, 20),
            ("cooldown_seconds", 300, 1, 86400),
            ("event_lease_seconds", 120, 10, 3600),
            ("delivery_retry_base_seconds", 5, 0, 300),
            ("delivery_retry_max_seconds", 300, 0, 3600),
            ("max_message_chars", 8000, 256, 50000),
            ("request_timeout_seconds", 30, 1, 120),
            ("delivery_max_stories", 20, 1, 100),
        ):
            config[name] = _bounded_int(
                self.get_int(
                    self._lark_environment_key(name.upper()),
                    self._lark_yaml_path(name),
                    default,
                ),
                default,
                minimum=minimum,
                maximum=maximum,
            )
        return config

    @property
    def feishu_app_id(self) -> str:
        """Compatibility alias for integrations that still use the old name."""
        return self.lark_app_id

    @property
    def feishu_app_secret(self) -> str:
        return self.lark_app_secret

    @property
    def feishu_allowed_users(self) -> tuple[str, ...]:
        return self.lark_allowed_users

    @property
    def feishu_config(self) -> dict[str, Any]:
        return self.lark_config

    @property
    def database_path(self) -> Path:
        return Path(self.get_str("DATABASE_PATH", "storage.local.data_dir", "output"))

    @property
    def ai_frontier_database_path(self) -> Path:
        return Path(
            self.get_str(
                "AI_FRONTIER_DB_PATH",
                "ai_frontier.database_path",
                "output/ai_frontier.db",
            )
        )

    @property
    def intelligence_enabled(self) -> bool:
        return self.get_bool("INTELLIGENCE_ENABLED", "intelligence.enabled", True)

    @property
    def intelligence_database_path(self) -> Path:
        return Path(
            self.get_str(
                "INTELLIGENCE_DB_PATH",
                "intelligence.database_path",
                "output/intelligence.db",
            )
        )

    @property
    def intelligence_require_existing(self) -> bool:
        """Require deployment roles to open a pre-migrated database."""
        return self.get_bool(
            "INTELLIGENCE_REQUIRE_EXISTING",
            "intelligence.require_existing",
            False,
        )

    @property
    def intelligence_sqlite_synchronous(self) -> str:
        """Return the SQLite durability mode used by intelligence writers."""
        value = self.get_str(
            "INTELLIGENCE_SQLITE_SYNCHRONOUS",
            "intelligence.sqlite_synchronous",
            "FULL",
        ).upper()
        if value not in {"OFF", "NORMAL", "FULL", "EXTRA"}:
            raise ValueError(
                "INTELLIGENCE_SQLITE_SYNCHRONOUS must be OFF, NORMAL, FULL, or EXTRA"
            )
        return value

    @property
    def intelligence_health_config(self) -> dict[str, Any]:
        """Return bounded local health thresholds and deployment expectations."""
        raw = self.yaml_value("intelligence.health", {})
        config = _thaw(raw) if isinstance(raw, Mapping) else {}
        config["require_source_runs"] = self.get_bool(
            "INTELLIGENCE_HEALTH_REQUIRE_SOURCE_RUNS",
            "intelligence.health.require_source_runs",
            False,
        )
        config["require_backup"] = self.get_bool(
            "INTELLIGENCE_HEALTH_REQUIRE_BACKUP",
            "intelligence.health.require_backup",
            False,
        )
        config["source_max_age_hours"] = _bounded_int(
            self.get_int(
                "INTELLIGENCE_HEALTH_SOURCE_MAX_AGE_HOURS",
                "intelligence.health.source_max_age_hours",
                6,
            ),
            6,
            minimum=1,
            maximum=168,
        )
        config["heartbeat_max_age_seconds"] = _bounded_int(
            self.get_int(
                "INTELLIGENCE_HEALTH_HEARTBEAT_MAX_AGE_SECONDS",
                "intelligence.health.heartbeat_max_age_seconds",
                60,
            ),
            60,
            minimum=10,
            maximum=86_400,
        )
        config["queue_wait_seconds"] = _bounded_int(
            self.get_int(
                "INTELLIGENCE_HEALTH_QUEUE_WAIT_SECONDS",
                "intelligence.health.queue_wait_seconds",
                300,
            ),
            300,
            minimum=10,
            maximum=86_400,
        )
        config["backup_max_age_hours"] = _bounded_int(
            self.get_int(
                "INTELLIGENCE_HEALTH_BACKUP_MAX_AGE_HOURS",
                "intelligence.health.backup_max_age_hours",
                26,
            ),
            26,
            minimum=1,
            maximum=720,
        )
        config["backup_dir"] = self.get_str(
            "TRENDRADAR_BACKUP_DIR",
            "intelligence.health.backup_dir",
            "output/backups",
        )
        configured_roles_env = self.get_str("TRENDRADAR_HEALTH_EXPECTED_ROLES", default="")
        configured_roles = (
            [role.strip() for role in configured_roles_env.split(",") if role.strip()]
            if configured_roles_env
            else config.get("expected_roles")
        )
        if not isinstance(configured_roles, list | tuple):
            configured_roles = []
        config["expected_roles"] = [str(role) for role in configured_roles if str(role).strip()]
        configured_sources_env = self.get_str("TRENDRADAR_HEALTH_EXPECTED_SOURCES", default="")
        configured_sources = (
            [source.strip() for source in configured_sources_env.split(",") if source.strip()]
            if configured_sources_env
            else config.get("expected_sources")
        )
        if not isinstance(configured_sources, list | tuple):
            configured_sources = []
        config["expected_sources"] = [
            str(source) for source in configured_sources if str(source).strip()
        ]
        return config

    @property
    def nvd_api_key(self) -> str:
        """Read the optional NVD credential from the environment only."""
        return self._environment_value("NVD_API_KEY") or ""

    @property
    def intelligence_story_config(self) -> dict[str, Any]:
        """Return mutable Story settings with explicit environment overrides."""
        raw = self.yaml_value("intelligence.story", {})
        config = _thaw(raw) if isinstance(raw, Mapping) else {}
        config["enabled"] = self.get_bool(
            "INTELLIGENCE_STORY_ENABLED",
            "intelligence.story.enabled",
            True,
        )
        config["output_dir"] = self.get_str(
            "INTELLIGENCE_STORY_OUTPUT_DIR",
            "intelligence.story.output_dir",
            "output/stories",
        )
        wording = config.get("wording")
        wording = dict(wording) if isinstance(wording, Mapping) else {}
        wording["enabled"] = self.intelligence_story_wording_enabled
        config["wording"] = wording
        config.setdefault("timezone", self.timezone)
        if self.has_environment("INTELLIGENCE_USER_INTERESTS"):
            ranking = config.setdefault("ranking", {})
            if isinstance(ranking, dict):
                ranking["user_interests"] = list(
                    self.get_csv("INTELLIGENCE_USER_INTERESTS")
                )
        return config

    @property
    def intelligence_assistant_config(self) -> dict[str, Any]:
        """Return bounded local Assistant settings with environment precedence."""
        raw = self.yaml_value("intelligence.assistant", {})
        config = _thaw(raw) if isinstance(raw, Mapping) else {}

        integer_settings = (
            ("session_ttl_days", "SESSION_TTL_DAYS", 30, 1, 3650),
            ("max_messages", "MAX_MESSAGES", 100, 2, 1000),
            ("max_history_messages", "MAX_HISTORY_MESSAGES", 12, 2, 100),
            ("max_context_chars", "MAX_CONTEXT_CHARS", 24_000, 512, 200_000),
            ("max_input_chars", "MAX_INPUT_CHARS", 8_000, 1, 50_000),
            ("max_output_chars", "MAX_OUTPUT_CHARS", 12_000, 1, 50_000),
            ("default_lookback_days", "LOOKBACK_DAYS", 7, 1, 3650),
            ("max_stories", "MAX_STORIES", 20, 1, 100),
            ("max_members_per_story", "MAX_MEMBERS_PER_STORY", 8, 1, 50),
            (
                "max_observations_per_story",
                "MAX_OBSERVATIONS_PER_STORY",
                16,
                1,
                100,
            ),
            ("max_items", "MAX_ITEMS", 20, 0, 100),
            ("max_citations", "MAX_CITATIONS", 12, 1, 100),
            ("max_tool_calls", "MAX_TOOL_CALLS", 3, 0, 3),
            ("max_tool_result_chars", "MAX_TOOL_RESULT_CHARS", 4_000, 256, 4_000),
        )
        config["enabled"] = self.get_bool(
            "INTELLIGENCE_ASSISTANT_ENABLED",
            "intelligence.assistant.enabled",
            True,
        )
        for name, env_suffix, default, minimum, maximum in integer_settings:
            config[name] = _bounded_int(
                self.get_int(
                    f"INTELLIGENCE_ASSISTANT_{env_suffix}",
                    f"intelligence.assistant.{name}",
                    default,
                ),
                default,
                minimum=minimum,
                maximum=maximum,
            )

        raw_tools = config.get("tools")
        tools = dict(raw_tools) if isinstance(raw_tools, Mapping) else {}
        for name in ("search_stories", "search_content_items", "get_story_evidence"):
            env_name = f"INTELLIGENCE_ASSISTANT_TOOL_{name.upper()}_ENABLED"
            tools[name] = self.get_bool(
                env_name,
                f"intelligence.assistant.tools.{name}",
                name in {"search_stories", "search_content_items", "get_story_evidence"},
            )
        config["tools"] = tools
        return config

    @property
    def intelligence_research_config(self) -> dict[str, Any]:
        """Return bounded opt-in research settings; no credential is read from YAML."""
        # Read only the documented fields. Arbitrary YAML keys must never become
        # executable names, provider selectors, or credential inputs.
        config = {}
        known = {
            "search_web", "search_github", "search_reddit",
            "read_webpage", "get_video_transcript",
        }
        configured = self.get_csv(
            "INTELLIGENCE_RESEARCH_CAPABILITIES", "intelligence.research.capabilities"
        )
        config["capabilities"] = [value for value in configured if value in known]
        config["enabled"] = self.get_bool(
            "INTELLIGENCE_RESEARCH_ENABLED", "intelligence.research.enabled", False
        )
        config["timeout_seconds"] = _bounded_int(
            self.get_int("INTELLIGENCE_RESEARCH_TIMEOUT_SECONDS",
                         "intelligence.research.timeout_seconds", 15),
            15, minimum=1, maximum=30,
        )
        config["max_results"] = _bounded_int(
            self.get_int("INTELLIGENCE_RESEARCH_MAX_RESULTS",
                         "intelligence.research.max_results", 5),
            5, minimum=1, maximum=10,
        )
        config["max_result_chars"] = _bounded_int(
            self.get_int("INTELLIGENCE_RESEARCH_MAX_RESULT_CHARS",
                         "intelligence.research.max_result_chars", 3000),
            3000, minimum=256, maximum=4000,
        )
        config["max_response_bytes"] = _bounded_int(
            self.get_int("INTELLIGENCE_RESEARCH_MAX_RESPONSE_BYTES",
                         "intelligence.research.max_response_bytes", 262_144),
            262_144, minimum=1024, maximum=1_048_576,
        )
        config["max_concurrency"] = _bounded_int(
            self.get_int("INTELLIGENCE_RESEARCH_MAX_CONCURRENCY",
                         "intelligence.research.max_concurrency", 2),
            2, minimum=1, maximum=4,
        )
        config["assistant_tool_enabled"] = self.get_bool(
            "INTELLIGENCE_ASSISTANT_TOOL_RESEARCH_EXTERNAL_ENABLED",
            "intelligence.assistant.tools.research_external",
            bool(config["enabled"]),
        )
        return config

    @property
    def intelligence_research_github_token(self) -> str | None:
        """Return the research-only GitHub secret without putting it in YAML config."""
        return (
            self._environment_value("INTELLIGENCE_RESEARCH_GITHUB_TOKEN")
        )

    @property
    def intelligence_security_config(self) -> dict[str, Any]:
        """Return mutable security settings without ever loading credentials from YAML."""
        raw = self.yaml_value("intelligence.security", None)
        if not isinstance(raw, Mapping):
            raw = self.yaml_value("security", {})
        config = _thaw(raw) if isinstance(raw, Mapping) else {}
        config.pop("nvd_api_key", None)
        sources = config.get("sources")
        if isinstance(sources, dict):
            nvd = sources.get("nvd")
            if isinstance(nvd, dict):
                nvd.pop("api_key", None)
        config["enabled"] = self.get_bool(
            "INTELLIGENCE_SECURITY_ENABLED",
            "intelligence.security.enabled",
            True,
        )
        config["output_dir"] = self.get_str(
            "INTELLIGENCE_SECURITY_OUTPUT_DIR",
            "intelligence.security.output_dir",
            "output/security",
        )
        config["max_concurrency"] = _bounded_int(
            self.get_int(
                "INTELLIGENCE_SECURITY_MAX_CONCURRENCY",
                "intelligence.security.max_concurrency",
                4,
            ),
            4,
            minimum=1,
            maximum=16,
        )
        config["stale_after_hours"] = _bounded_int(
            self.get_int(
                "INTELLIGENCE_SECURITY_STALE_AFTER_HOURS",
                "intelligence.security.stale_after_hours",
                48,
            ),
            48,
            minimum=1,
            maximum=8760,
        )
        config.setdefault("timezone", self.timezone)
        return config

    def __repr__(self) -> str:
        configured_secrets = sum(
            bool(value)
            for value in (
                self.gemini_api_key,
                self.lark_app_id,
                self.lark_app_secret,
                self.nvd_api_key,
            )
        )
        return (
            "RuntimeSettings("
            f"config_path={self.config_path!r}, "
            f"configured_secrets={'<redacted>' if configured_secrets else 0}"
            ")"
        )


def load_settings(
    config_path: str | Path | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    fallback_to_empty: bool = False,
) -> RuntimeSettings:
    """Load settings using explicit path, ``CONFIG_PATH``, then the repository default."""
    source_environ = os.environ if environ is None else environ
    frozen_environ = MappingProxyType({str(key): str(value) for key, value in source_environ.items()})
    selected_path = config_path
    if selected_path is None:
        selected_path = str(source_environ.get("CONFIG_PATH", "")).strip() or DEFAULT_CONFIG_PATH
    path = Path(selected_path)
    try:
        raw_config = _discard_gemini_credentials(load_yaml_config(path))
        for section_name in ("lark", "feishu"):
            section = raw_config.get(section_name)
            if isinstance(section, dict):
                for name in ("app_id", "app_secret", "verification_token", "encrypt_key"):
                    section.pop(name, None)
    except (OSError, ValueError, yaml.YAMLError):
        if not fallback_to_empty:
            raise
        raw_config = {}
    return RuntimeSettings(
        config_path=path,
        _raw_config=_freeze(raw_config),
        _environ=frozen_environ,
    )


__all__ = ["RuntimeSettings", "load_settings", "load_yaml_config"]
