@echo off
cd /d "C:\Stylefit Vibe Code\stylefit-web"
:loop
echo [%date% %time%] Starting StyleFit Server...
"C:\Users\PC\AppData\Local\Programs\Python\Python312\python.exe" server.py
echo [%date% %time%] Server process stopped with exit code %errorlevel%. Restarting in 2s...
ping 127.0.0.1 -n 3 >nul
goto loop

