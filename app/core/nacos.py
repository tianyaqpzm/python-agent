import nacos
import socket
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)


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

    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("10.255.255.255", 1))
            IP = s.getsockname()[0]
        except Exception:
            IP = "127.0.0.1"
        finally:
            s.close()
        return IP

    def connect(self):
        """
        🔥 新增方法：显式建立连接
        只有在 main.py 的 lifespan 中调用此方法时，才会真正发起网络请求
        """
        if self.client:
            return  # 已经连过了，直接返回

        try:
            logger.info(f"🔌 Connecting to Nacos at {self.server_addr}...")
            self.client = nacos.NacosClient(
                self.server_addr,
                namespace=self.namespace,
                username=self.username,
                password=self.password,
            )
            logger.info("✅ Connected to Nacos successfully.")
        except Exception as e:
            logger.error(f"❌ Failed to connect to Nacos: {e}")
            raise e  # 抛出异常，让外部的重试逻辑捕获

    def register_service(self):
        # 如果还没连接，先尝试连接
        if not self.client:
            self.connect()

        try:
            # 🔥 这里的配置保持你之前的修复逻辑不变
            self.client.add_naming_instance(
                self.service_name,
                self.ip,
                self.port,
                cluster_name="DEFAULT",
                heartbeat_interval=10,
                ephemeral=True,
            )
            logger.info(
                f"✅ Registered service {self.service_name} at {self.ip}:{self.port}"
            )
        except Exception as e:
            logger.error(f"❌ Failed to register service: {e}")
            # 这里可以选择是否抛出异常，取决于你希望注册失败是否影响启动

    def deregister_service(self):
        if not self.client:
            return

        try:
            self.client.remove_naming_instance(self.service_name, self.ip, self.port)
            logger.info(f"✅ Deregistered service {self.service_name}")
        except Exception as e:
            logger.error(f"Failed to deregister service: {e}")

    def get_service(self, service_name):
        if not self.client:
            self.connect()

        try:
            return self.client.list_naming_instance(service_name)
        except Exception as e:
            logger.error(f"Failed to get service {service_name}: {e}")
            return []

    def get_config(self, data_id, group):
        if not self.client:
            self.connect()
        try:
            return self.client.get_config(data_id, group)
        except Exception as e:
            logger.error(f"Failed to get config {data_id}: {e}")
            return None

    def add_config_watcher(self, data_id, group, cb):
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
    port=settings.PORT,
)
