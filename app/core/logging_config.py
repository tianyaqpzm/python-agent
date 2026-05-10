import logging
import logging.handlers
import os
import gzip
import shutil
from datetime import datetime

class GzipRotator:
    def __call__(self, source, dest):
        with open(source, 'rb') as f_in:
            with gzip.open(f'{dest}.gz', 'wb') as f_out:
                shutil.copyfileobj(f_in, f_out)
        os.remove(source)

def namer(name):
    return f"{name}.{datetime.now().strftime('%Y-%m-%d')}"

def setup_logging(log_dir="logs"):
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    # 1. 基础配置
    log_format = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # 2. 业务日志 Handler (App)
    app_handler = logging.handlers.TimedRotatingFileHandler(
        os.path.join(log_dir, "app.log"),
        when='D',
        interval=1,
        backupCount=30,
        encoding='utf-8'
    )
    app_handler.setFormatter(log_format)
    app_handler.rotator = GzipRotator()
    app_handler.namer = namer

    # 3. Nacos SDK 日志 Handler
    nacos_handler = logging.handlers.TimedRotatingFileHandler(
        os.path.join(log_dir, "nacos.log"),
        when='D',
        interval=1,
        backupCount=15, # Nacos 日志保留 15 天即可
        encoding='utf-8'
    )
    nacos_handler.setFormatter(log_format)
    nacos_handler.rotator = GzipRotator()
    nacos_handler.namer = namer

    # 4. 控制台 Handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_format)

    # 5. 配置 Root Logger (应用日志)
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
    root_logger.addHandler(app_handler)
    root_logger.addHandler(console_handler)

    # 6. 配置 Nacos Logger (独立流向)
    nacos_logger = logging.getLogger("nacos")
    nacos_logger.propagate = False # 防止 Nacos 日志流入 Root Logger
    nacos_logger.setLevel(logging.INFO)
    nacos_logger.addHandler(nacos_handler)
    
    # nacos.client 也需要单独处理，因为它可能不完全遵循父级配置
    nacos_client_logger = logging.getLogger("nacos.client")
    nacos_client_logger.propagate = False
    nacos_client_logger.addHandler(nacos_handler)

    logging.info("✅ Logging system initialized with Gzip rotation.")
