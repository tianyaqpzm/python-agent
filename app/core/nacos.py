import nacos
import socket
import logging
from app.core.config import settings

logger = logging.getLogger(__name__)

class NacosManager:
    def __init__(self, server_addr, username, password, namespace, service_name, ip=None, port=8181):
        self.server_addr = server_addr
        self.namespace = namespace
        self.service_name = service_name
        self.port = port
        self.ip = ip or self._get_local_ip()
        self.client = nacos.NacosClient(
            server_addr, 
            namespace=namespace, 
            username=username, 
            password=password
        )

    def _get_local_ip(self):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            # Doesn't even have to be reachable
            s.connect(('10.255.255.255', 1))
            IP = s.getsockname()[0]
        except Exception:
            IP = '127.0.0.1'
        finally:
            s.close()
        return IP

    def register_service(self):
        try:
            # 🔥【关键修复】必须手动指定这两个参数，否则 0.1.15 配合 Nacos 2.x 必死
            self.client.add_naming_instance(self.service_name, self.ip, self.port,cluster_name="DEFAULT",
            heartbeat_interval=5, # <--- 加在这里！强制定义心跳间隔
            ephemeral=True)
            logger.info(f"Registered service {self.service_name} at {self.ip}:{self.port}")
        except Exception as e:
            logger.error(f"Failed to register service: {e}")

    def deregister_service(self):
        try:
            self.client.remove_naming_instance(self.service_name, self.ip, self.port)
            logger.info(f"Deregistered service {self.service_name}")
        except Exception as e:
            logger.error(f"Failed to deregister service: {e}")
    
    def get_service(self, service_name):
        try:
            return self.client.list_naming_instance(service_name)
        except Exception as e:
            logger.error(f"Failed to get service {service_name}: {e}")
            return []

# Singleton instance
nacos_manager = NacosManager(
    server_addr=settings.NACOS_SERVER_ADDR,
    namespace=settings.NACOS_NAMESPACE,
    username=settings.NACOS_USERNAME,
    password=settings.NACOS_PASSWORD,
    service_name=settings.SERVICE_NAME,
    port=settings.PORT
)
