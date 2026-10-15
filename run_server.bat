@echo off
cd /d "C:\Stylefit Vibe Code\stylefit-web"
:loop
echo [%date% %time%] Starting StyleFit Server...
"C:\Users\PC\AppData\Local\Programs\Python\Python312\python.exe" server.py
echo [%date% %time%] Server process stopped with exit code %errorlevel%. Restarting in 2s...
timeout /t 2 /nobreak >nul
goto loop

