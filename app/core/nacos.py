import nacos
import socket
import logging
import asyncio
import time
from typing import Optional, Any
from app.core.config import settings

logger = logging.getLogger(__name__)

# 🔥 动态调整 Nacos SDK 默认超时时间
try:
    import nacos.client
    nacos.client.DEFAULTS["TIMEOUT"] = settings.NACOS_TIMEOUT
    logger.info(f"⚙️ Set Nacos default timeout to {settings.NACOS_TIMEOUT}s")
except Exception as e:
    logger.warning(f"⚠️ Failed to patch Nacos timeout: {e}")


class NacosManager:
    def __init__(
        self,
        server_addr,
        username,
        password,
        namespace,
        service_name,
        ip=None,
        port=8181,
    ):
        # 1. 保存基础配置
        self.server_addr = server_addr
        self.namespace = namespace
        self.service_name = service_name
        self.port = port
        self.ip = ip or self._get_local_ip()

        # 2. 保存凭证 (因为连接推迟了，所以必须先存起来)
        self.username = username
        self.password = password

        # 3. 🔥 关键修改：初始化时 client 设为 None，不立即连接
        self.client = None

    def _get_local_ip(self) -> str:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            IP = s.getsockname()[0]
        except OSError:
            IP = "127.0.0.1"
        finally:
            s.close()
        return IP

    def connect(self) -> None:
        """
        🔥 显式建立连接，包含重试机制
        """
        if self.client:
            return

        retries = settings.NACOS_RETRIES
        delay = 2  # 初始重试延迟

        for i in range(retries):
            try:
                logger.info(f"🔌 Connecting to Nacos at {self.server_addr} (Attempt {i+1}/{retries})...")
                self.client = nacos.NacosClient(
                    self.server_addr,
                    namespace=self.namespace,
                    username=self.username,
                    password=self.password,
                )
                logger.info("✅ Connected to Nacos successfully.")
                return
            except Exception as e:
                logger.warning(f"❌ Connection attempt {i+1} failed: {e}")
                if i < retries - 1:
                    logger.info(f"⏳ Retrying in {delay}s...")
                    time.sleep(delay)
                    delay *= 2  # 指数退避
                else:
                    logger.error("🚫 All Nacos connection attempts failed.")
                    raise e

    def register_service(self) -> None:
        # 如果还没连接，先尝试连接
        if not self.client:
            self.connect()

        try:
            self.client.add_naming_instance(
                self.service_name,
                self.ip,
                self.port,
                cluster_name="DEFAULT",
                heartbeat_interval=settings.NACOS_HEARTBEAT_INTERVAL,
                ephemeral=True,
            )
            logger.info(
                f"✅ Registered service {self.service_name} at {self.ip}:{self.port}"
            )
        except Exception as e:
            logger.error(f"❌ Failed to register service: {e}")

    def deregister_service(self) -> None:
        if not self.client:
            return

        try:
            self.client.remove_naming_instance(self.service_name, self.ip, self.port)
            logger.info(f"✅ Deregistered service {self.service_name}")
        except Exception as e:
            logger.error(f"Failed to deregister service: {e}")

    def get_service(self, service_name: str, group_name: Optional[str] = None) -> list[dict]:
        """
        获取服务实例列表，仅返回健康且启用的实例。
        """
        if not self.client:
            self.connect()

        try:
            group = group_name or settings.NACOS_GROUP
            res = self.client.list_naming_instance(service_name, group_name=group)
            
            # Nacos SDK 返回的是完整响应字典，我们需要提取 hosts 列表
            if isinstance(res, dict) and "hosts" in res:
                instances = res["hosts"]
                # 过滤出健康且启用的实例
                return [
                    i for i in instances 
                    if i.get("healthy") and i.get("enabled")
                ]
            
            # 如果已经是列表（防御性处理），直接过滤
            if isinstance(res, list):
                return [
                    i for i in res 
                    if i.get("healthy") and i.get("enabled")
                ]
                
            return []
        except Exception as e:
            logger.error(f"Failed to get service {service_name} from group {group_name}: {e}")
            return []

    def get_config(self, data_id: str, group: str) -> Optional[str]:
        if not self.client:
            self.connect()
        try:
            logger.debug(f"🔍 Fetching Nacos config: DataID={data_id}, Group={group}, Namespace={self.namespace}")
            return self.client.get_config(data_id, group)
        except Exception as e:
            logger.error(f"❌ Failed to get config {data_id} from Group {group}: {e}")
            return None

    def add_config_watcher(self, data_id: str, group: str, cb: Any) -> None:
        if not self.client:
            self.connect()
        try:
            self.client.add_config_watcher(data_id, group, cb)
            logger.info(f"👀 Watching config: {data_id} (Group: {group})")
        except Exception as e:
            logger.error(f"Failed to add config watcher for {data_id}: {e}")


# Singleton instance
# 🔥 这里实例化现在是非常安全的，因为它只赋值变量，不发请求
nacos_manager = NacosManager(
    server_addr=settings.NACOS_SERVER_ADDR,
    namespace=settings.NACOS_NAMESPACE,
    username=settings.NACOS_USERNAME,
    password=settings.NACOS_PASSWORD,
    service_name=settings.SERVICE_NAME,
    ip=settings.SERVICE_IP,
    port=settings.PORT,
)
