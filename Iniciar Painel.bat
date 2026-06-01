@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Cortex - Painel de Vendas
echo.
echo  ===========================================
echo   Cortex - Painel de Vendas
echo   Subindo o servidor... aguarde uns segundos.
echo   O navegador abre sozinho em http://localhost:8000
echo   (para fechar o painel: feche esta janela)
echo  ===========================================
echo.

REM abre o navegador depois de ~3s (tempo do servidor subir)
start "" /b cmd /c "ping 127.0.0.1 -n 4 >nul & start """" http://localhost:8000"

REM sobe o servidor (usa o python do .venv se existir, senao o do sistema)
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -m uvicorn app:app --port 8000
) else (
  python -m uvicorn app:app --port 8000
)

echo.
echo  Servidor encerrado.
pause
