import yaml
import os
import logging

logger = logging.getLogger(__name__)

class Settings:
    _instance = None
    _config = {}

    def __new__(cls, config_path="config.yaml"):
        if cls._instance is None:
            cls._instance = super(Settings, cls).__new__(cls)
            cls._instance._load_config(config_path)
        return cls._instance
        
    def _load_config(self, config_path):
        if not os.path.exists(config_path):
            logger.warning(f"Config file {config_path} not found. Using defaults.")
            return
            
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                self._config = yaml.safe_load(f) or {}
        except Exception as e:
            logger.error(f"Error loading config.yaml: {e}")

    def get(self, key_path, default=None):
        keys = key_path.split('.')
        value = self._config
        try:
            for k in keys:
                value = value[k]
            return value
        except (KeyError, TypeError):
            return default

def get_settings():
    return Settings()
