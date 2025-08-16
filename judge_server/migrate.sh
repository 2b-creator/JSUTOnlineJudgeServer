rm -rf /home/tim/Projects/JSUTOnlineJudgeServer/judge_server/judge/migrations
rm db.sqlite3
python manage.py makemigrations judge
python manage.py migrate
python manage.py createsuperuser
