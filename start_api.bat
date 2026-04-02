@echo off
echo Starting API on http://127.0.0.1:8080 ...
cd /d "D:\Trampo\Projeto Playlist"
py -m uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
