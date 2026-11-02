import logging
import os
from app.utils.platform_binaries import get_base_resource_dir

try:
    import yaml
except ImportError:
    yaml = None

logger = logging.getLogger(__name__)


def _simple_yaml_parse(text: str) -> dict:
    """Fallback parser for simple two-level key: value YAML files if PyYAML is unavailable."""
    result = {}
    current_section = None
    for raw_line in text.splitlines():
        line = raw_line.split("#", 1)[0].rstrip()
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        stripped = line.strip()
        if ":" not in stripped:
            continue
        k, v = stripped.split(":", 1)
        k = k.strip()
        v = v.strip()
        if indent == 0 and not v:
            current_section = {}
            result[k] = current_section
        else:
            parsed_v = v
            if v.isdigit():
                parsed_v = int(v)
            else:
                try:
                    parsed_v = float(v)
                except ValueError:
                    parsed_v = v.strip("\"'")
            if indent > 0 and isinstance(current_section, dict):
                current_section[k] = parsed_v
            else:
                result[k] = parsed_v
    return result


class Settings:
    _instance = None
    _config = {}

    def __new__(cls, config_path="config.yaml"):
        if cls._instance is None:
            cls._instance = super(Settings, cls).__new__(cls)
            cls._instance._load_config(config_path)
        return cls._instance

    def _load_config(self, config_path):
        candidates = [
            config_path,
            os.path.join(get_base_resource_dir(), config_path),
            os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", config_path)),
        ]
        resolved_path = None
        for c in candidates:
            if os.path.isfile(c):
                resolved_path = c
                break

        if not resolved_path:
            logger.warning(f"Config file {config_path} not found. Using defaults.")
            return

        try:
            with open(resolved_path, "r", encoding="utf-8") as f:
                raw = f.read()
                if yaml is not None:
                    self._config = yaml.safe_load(raw) or {}
                else:
                    self._config = _simple_yaml_parse(raw)
        except Exception as e:
            logger.error(f"Error loading config.yaml: {e}")

    def get(self, key_path, default=None):
        keys = key_path.split(".")
        value = self._config
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default


def get_settings():
    return Settings()
