import logging
import yaml
from app.core.config import settings
from app.core.nacos import nacos_manager

logger = logging.getLogger(__name__)


class DynamicConfig:
    def __init__(self):
        # Default to environment variables
        self.llm_provider = settings.LLM_PROVIDER
        self.llm_base_url = settings.LLM_BASE_URL
        self.llm_model = settings.LLM_MODEL

        # Nacos Config Info
        self.data_id = "python-agent.yaml"
        self.group = "DEFAULT_GROUP"

    def watch_config(self):
        """Start watching for configuration changes."""
        logger.info(f"🎧 Starting to watch config: {self.data_id}")

        # 1. Get initial config
        content = nacos_manager.get_config(self.data_id, self.group)
        if content:
            self._update_config(content)

        # 2. Add watcher
        nacos_manager.add_config_watcher(self.data_id, self.group, self._update_config)

    def _update_config(self, args):
        """Callback for Nacos config updates."""
        try:
            # args can be the content string directly or a dictionary depending on SDK version
            # Usually it's the content string in the callback
            content = args
            if isinstance(args, dict):
                content = args.get("content", "")

            if not content:
                logger.warning("⚠️ Received empty config update from Nacos")
                return

            logger.info("🔄 Received config update from Nacos")
            config = yaml.safe_load(content)

            if config:
                # Update LLM settings if present
                if "llm" in config:
                    llm_config = config["llm"]
                    self.llm_provider = llm_config.get("provider", self.llm_provider)
                    self.llm_base_url = llm_config.get("base_url", self.llm_base_url)
                    self.llm_model = llm_config.get("model", self.llm_model)

                    logger.info(
                        f"✅ LLM Config Updated: Provider={self.llm_provider}, Model={self.llm_model}"
                    )

        except Exception as e:
            logger.error(f"❌ Error updating config: {e}")


# Singleton instance
dynamic_config = DynamicConfig()
