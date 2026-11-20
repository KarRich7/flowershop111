@echo off
cd /d "%~dp0"
docker compose run --rm vk-parser menu
exit /b %errorlevel%
