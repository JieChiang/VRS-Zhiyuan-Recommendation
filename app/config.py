from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_private_environment(project_root: Path = PROJECT_ROOT) -> None:
    """Process env > explicit env file > project .env > user private fallback."""
    explicit = os.getenv("VRS_ENV_FILE", "").strip()
    if explicit:
        load_dotenv(Path(explicit).expanduser(), override=False)
    load_dotenv(project_root / ".env", override=False)
    private_root = Path(os.environ.get("APPDATA") or Path.home() / ".config")
    load_dotenv(private_root / "VRS" / "private.env", override=False)


load_private_environment()


def _load_yaml_config(project_root: Path) -> Dict[str, Any]:
    config_path = project_root / "setting.yaml"
    if not config_path.exists():
        return {}
    try:
        raw = config_path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        data = yaml.safe_load(raw) or {}
        if isinstance(data, dict):
            return data
        return {}
    except Exception:
        return {}


def _pick(config_data: Dict[str, Any], env_name: str, default: Any, *path: str) -> Any:
    # 本机 .env / 部署环境优先，避免旧 YAML 配置覆盖新密钥和模型。
    if os.getenv(env_name, "").strip():
        return os.environ[env_name]
    cur: Any = config_data
    for key in path:
        if not isinstance(cur, dict) or key not in cur:
            cur = None
            break
        cur = cur[key]
    if cur is None or cur == "":
        return os.getenv(env_name, default)
    return cur


_YAML_CONFIG = _load_yaml_config(PROJECT_ROOT)


@dataclass(frozen=True)
class Settings:
    neo4j_url: str = str(_pick(_YAML_CONFIG, "NEO4J_URL", "http://localhost:7474", "neo4j", "url"))
    neo4j_db: str = str(_pick(_YAML_CONFIG, "NEO4J_DB", "neo4j", "neo4j", "database"))
    neo4j_user: str = str(_pick(_YAML_CONFIG, "NEO4J_USER", "neo4j", "neo4j", "username"))
    neo4j_password: str = field(default=str(_pick(_YAML_CONFIG, "NEO4J_PASSWORD", "", "neo4j", "password")), repr=False)
    deepseek_api_key: str = field(default=str(
        _pick(_YAML_CONFIG, "DEEPSEEK_API_KEY", _pick(_YAML_CONFIG, "DEEPSEEK_API_KEY", "", "apikey"), "deepseek", "api_key")
    ), repr=False)
    deepseek_base_url: str = str(_pick(_YAML_CONFIG, "DEEPSEEK_BASE_URL", "https://api.deepseek.com", "deepseek", "base_url"))
    deepseek_model: str = str(_pick(_YAML_CONFIG, "DEEPSEEK_MODEL", "deepseek-flash", "deepseek", "model"))
    deepseek_timeout: int = int(_pick(_YAML_CONFIG, "DEEPSEEK_TIMEOUT", 60, "deepseek", "timeout"))
    ollama_base_url: str = str(_pick(_YAML_CONFIG, "OLLAMA_BASE_URL", "http://localhost:11434/v1", "ollama", "base_url"))
    ollama_model: str = str(_pick(_YAML_CONFIG, "OLLAMA_MODEL", "deepseek-r1:8b", "ollama", "model"))
    ollama_timeout: int = int(_pick(_YAML_CONFIG, "OLLAMA_TIMEOUT", 90, "ollama", "timeout"))
    tesseract_cmd: str = str(_pick(_YAML_CONFIG, "TESSERACT_CMD", "tesseract", "ocr", "tesseract_cmd"))
    app_host: str = str(_pick(_YAML_CONFIG, "APP_HOST", "127.0.0.1", "app", "host"))
    app_port: int = int(_pick(_YAML_CONFIG, "APP_PORT", 8000, "app", "port"))
    project_root: Path = PROJECT_ROOT
    storage_dir: Path = project_root / "storage"


settings = Settings()
