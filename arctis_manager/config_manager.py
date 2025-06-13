import json
import os
from pathlib import Path
from typing import Optional, Dict, Any
import logging

_MINIMAL_EMERGENCY_CONFIG = {
    "device_item_visibility": {
        "Default": {
            "sections.battery": {
                "menu.headset_power_status": True,
                "menu.headset_battery_charge": True
            }
        }
    }
}

class ConfigManager:
    _instance = None
    config_path: Path
    all_device_configs: Optional[Dict[str, Any]] = None
    default_device_config: Optional[Dict[str, Any]] = None

    @staticmethod
    def get_instance():
        if ConfigManager._instance is None:
            ConfigManager._instance = ConfigManager()
        return ConfigManager._instance

    def __init__(self):
        if ConfigManager._instance is not None:
            raise Exception("This class is a singleton!")
        else:
            ConfigManager._instance = self
            config_home = os.getenv('XDG_CONFIG_HOME', os.path.expanduser('~/.config'))
            self.config_path = Path(config_home).joinpath('arctis_manager')
            self.config_path.mkdir(parents=True, exist_ok=True)
            self.all_device_configs = None
            self.default_device_config = None

    def get_config(self, vendor_id: int, product_id: int) -> Optional[dict]:
        config_file_path = self.config_path.joinpath(f'device_{hex(vendor_id)[2:]}_{hex(product_id)[2:]}.json')
        if config_file_path.is_file():
            return json.load(config_file_path.open('r'))

        return None

    def save_config(self, vendor_id: int, product_id: int, config: dict):
        config_file_path = self.config_path.joinpath(f'device_{hex(vendor_id)[2:]}_{hex(product_id)[2:]}.json')
        with config_file_path.open('w') as f:
            json.dump(config, f)

    def load_sections_config(self, log: logging.Logger):
        if self.all_device_configs is not None and self.default_device_config is not None:
            return

        config_file_path = self.config_path.joinpath('sections_config.json')
        
        loaded_config = _MINIMAL_EMERGENCY_CONFIG
        try:
            with open(config_file_path, 'r') as f:
                loaded_config = json.load(f)
        except FileNotFoundError:
            log.warning(f"Config file {config_file_path} not found. Creating a default one.")
            try:
                config_file_path.parent.mkdir(parents=True, exist_ok=True)
                with open(config_file_path, 'w') as f:
                    json.dump(loaded_config, f, indent=2)
                log.info(f"Created default sections_config.json at {config_file_path}")
            except OSError as e:
                log.error(f"Failed to create default config file {config_file_path}: {e}")
        except json.JSONDecodeError as e:
            log.error(f"Error decoding {config_file_path}: {e}. Using emergency default for this session.")
        
        emergency_visibility = _MINIMAL_EMERGENCY_CONFIG.get("device_item_visibility", {})
        self.all_device_configs = loaded_config.get("device_item_visibility", emergency_visibility)
        self.default_device_config = self.all_device_configs.setdefault(
            "Default", emergency_visibility.get("Default", {})
        )

    def get_device_config(self, device_name: str, log: logging.Logger) -> Dict[str, Any]:
        self.load_sections_config(log)

        best_match_key = None
        for config_key in self.all_device_configs.keys():
            if config_key == "Default":
                continue
            if config_key in device_name:
                if best_match_key is None or len(config_key) > len(best_match_key):
                    best_match_key = config_key
        
        return self.all_device_configs.get(best_match_key, self.default_device_config)
