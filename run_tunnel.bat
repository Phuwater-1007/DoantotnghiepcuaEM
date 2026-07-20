@echo off
title Cloudflare Tunnel (fuswater.online)
cd /d "%~dp0"
echo ========================================================
echo   KICH HOAT DUONG TRUYEN CLOUDFLARE (fuswater.online)
echo ========================================================
echo.
cloudflared.exe tunnel run --token eyJhIjoiYTA1ZjQzMWRjNWI2ZDIwYWIyYWE2NzFmYTQ2ODY0ZjkiLCJ0IjoiMzA2ZDU3NTEtNGNjYi00MjZmLTkyZmYtZDZlMjY0N2U0NGJkIiwicyI6Ik9UazVPRFZoTTJFdE5XVmlZeTAwWW1aa0xXRXhNRGd0Tm1SaU9XSXhNRGxtTldOaiJ9
pause
