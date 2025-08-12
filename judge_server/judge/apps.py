from django.apps import AppConfig
from apscheduler.schedulers.background import BackgroundScheduler
from judge_server.judge.models import DomServerSave


class JudgeConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'judge'

    def ready(self):
        # 创建调度器实例（单例模式）
        if not hasattr(self, 'scheduler'):
            self.scheduler = BackgroundScheduler()
            self.scheduler.start()
            # 添加关闭钩子
            import atexit
            atexit.register(lambda: self.scheduler.shutdown())
        DomServerSave.objects.update_or_create(
            singleton_id=1,
            defaults={
                'admin': 'admin',
                'init_passwd': 'settings.DOM_INIT_PASSWD',
                'api_key': 'settings.DOM_API_KEY'
            }
        )
