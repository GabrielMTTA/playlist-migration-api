@echo off
echo Starting Celery Worker...
cd /d "D:\Trampo\Projeto Playlist"
py -m celery -A app.workers.celery_app worker --loglevel=info --pool=solo
