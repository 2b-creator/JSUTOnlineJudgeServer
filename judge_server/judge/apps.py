from django.apps import AppConfig
from apscheduler.schedulers.background import BackgroundScheduler
import logging

logger = logging.getLogger(__name__)

class JudgeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'judge'

    def ready(self):
        # 确保只初始化一次
        if not hasattr(self, 'scheduler'):
            logger.info("🚀 Starting APScheduler...")
            
            # 创建实例属性
            self.scheduler = BackgroundScheduler()
            self.scheduler.start()
            
            import atexit
            atexit.register(lambda: self.scheduler.shutdown())
            
            logger.info("✅ APScheduler started successfully")