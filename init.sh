django-admin startproject judge_server
cd judge_server
python manage.py startapp judge

celery -A judge_server.celery_app worker --loglevel=info