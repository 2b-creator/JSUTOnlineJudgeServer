from django.core.management.base import BaseCommand
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.date import DateTrigger
from django.utils import timezone
from datetime import datetime, timedelta
from judge.tasks import my_scheduled_task  # 导入你的任务函数
import uuid

def start_scheduler():
    scheduler = BlockingScheduler(timezone=timezone.get_current_timezone())

    # 设置未来某个时间点（例如 5 分钟后）
    run_time = datetime.now() + timedelta(minutes=5)

    scheduler.add_job(
        my_scheduled_task,
        trigger=DateTrigger(run_date=run_time),
        id=uuid.uuid4()
    )

    try:
        scheduler.start()
    except KeyboardInterrupt:
        scheduler.shutdown()


class Command(BaseCommand):
    help = 'Runs APScheduler'

    def handle(self, *args, **options):
        start_scheduler()
