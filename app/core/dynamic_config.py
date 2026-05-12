import logging
from typing import Dict, List, Any
import yaml
from app.core.config import settings
from app.core.nacos import nacos_manager

logger = logging.getLogger(__name__)

class DynamicConfig:
    def __init__(self):
        # 引导参数（必须通过环境变量获取，用于连接 Nacos）
        self.data_id = f"{settings.SERVICE_NAME}-{settings.APP_ENV}.yaml"
        self.group = settings.NACOS_GROUP
        # 注意：此处不再主动同步 settings，等待 watch_config 被显式调用后再初始化

    def _sync_from_settings(self):
        """从 settings 中同步所有大写配置项为实例的小写属性。"""
        for attr in dir(settings):
            if not attr.startswith("_") and attr.isupper():
                val = getattr(settings, attr)
                if not callable(val):
                    setattr(self, attr.lower(), val)

    def __getattr__(self, name: str):
        """兜底逻辑：如果实例属性不存在，尝试从 settings 获取。"""
        # 统一转换为大写尝试匹配 settings
        settings_key = name.upper()
        if hasattr(settings, settings_key):
            val = getattr(settings, settings_key)
            logger.info(f"ℹ️ Attribute '{name}' not found in DynamicConfig, falling back to settings.{settings_key}")
            return val
        raise AttributeError(f"'{self.__class__.__name__}' object has no attribute '{name}'")

    def watch_config(self):
        """启动配置监听。"""
        logger.info(f"🎧 Nacos Bootstrap: Targeting {self.data_id}")

        content = nacos_manager.get_config(self.data_id, self.group)
        if content:
            self._update_config(content)
            logger.info(f"✅ [Nacos] Config loaded and attributes initialized from {self.data_id}.")
        else:
            logger.warning(f"⚠️ [Nacos] Failed to load {self.data_id} or config is empty. Falling back to default settings.")
            self._sync_from_settings()

        nacos_manager.add_config_watcher(self.data_id, self.group, self._update_config)

    def _flatten_dict(self, d: Dict[str, Any], parent_key: str = '', sep: str = '_') -> Dict[str, Any]:
        items: List[tuple[str, Any]] = []
        for k, v in d.items():
            new_key = f"{parent_key}{sep}{k}" if parent_key else k
            if isinstance(v, dict):
                items.extend(self._flatten_dict(v, new_key, sep=sep).items())
            else:
                items.append((new_key, v))
        return dict(items)

    def _update_config(self, args: Any) -> None:
        """获取嵌套 YAML，智能映射并同步。"""
        try:
            content = args.get("content", "") if isinstance(args, dict) else args
            if not content: return

            raw_config = yaml.safe_load(content)
            if not isinstance(raw_config, dict): return

            flat_config = self._flatten_dict(raw_config)
            
            for key, value in flat_config.items():
                key_upper = key.upper()
                
                # 智能匹配逻辑：
                # 1. 直接匹配 (如 PG_HOST)
                # 2. 去掉前缀匹配 (如 APP_SERVICE_NAME -> SERVICE_NAME, SERVER_HOST -> HOST)
                target_key = None
                prefixes_to_strip = ["APP_", "SERVER_", "NACOS_"]
                
                if hasattr(settings, key_upper):
                    target_key = key_upper
                else:
                    for prefix in prefixes_to_strip:
                        if key_upper.startswith(prefix):
                            stripped_key = key_upper[len(prefix):]
                            if hasattr(settings, stripped_key):
                                target_key = stripped_key
                                break

                if target_key:
                    self._apply_setting(target_key, value)
            
            # 只有当所有的配置更新操作完成后，如果涉及到数据库变更，执行一次性的重置操作
            if any(key.startswith("PG_") for key in flat_config.keys()):
                from app.core.database import reset_engine
                reset_engine()
            
            logger.info("✅ Configuration synchronized and settings updated.")
        except Exception as e:
            logger.error(f"❌ YAML Processing Error: {e}")

    def _apply_setting(self, key: str, value: Any) -> None:
        """将值应用到 settings，并处理数据类型。"""
        old_val = getattr(settings, key)
        try:
            if isinstance(old_val, int): value = int(value)
            elif isinstance(old_val, float): value = float(value)
            elif isinstance(old_val, bool) and isinstance(value, str):
                value = value.lower() in ("true", "1", "yes")
        except (ValueError, TypeError) as e:
            logger.debug(f"Failed to cast {key} value {value} to {type(old_val)}: {e}")
            return

        setattr(settings, key, value)
        # 同时更新 dynamic_config 实例本身以保持一致
        setattr(self, key.lower(), value)

dynamic_config = DynamicConfig()
