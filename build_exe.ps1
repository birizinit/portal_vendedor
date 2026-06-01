# Gera o executável Windows em dist\Cortex\
# Requer: Python 3.10+ e venv com requirements instalados

$ErrorActionPreference = "Stop"
$Root = $PSScriptRoot
Set-Location $Root

$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) {
    Write-Host "Criando ambiente virtual…"
    python -m venv .venv
    $Py = Join-Path $Root ".venv\Scripts\python.exe"
}

Write-Host "Instalando dependências…"
& $Py -m pip install -q -r requirements.txt
& $Py -m pip install -q pyinstaller>=6.0

Write-Host "Gerando Cortex.exe (pode levar alguns minutos)…"
& $Py -m PyInstaller cortex.spec --noconfirm

$Dist = Join-Path $Root "dist\Cortex"
if (Test-Path $Dist) {
    Copy-Item (Join-Path $Root ".env.example") $Dist -Force -ErrorAction SilentlyContinue
    Copy-Item (Join-Path $Root "LEIA-ME-INSTALACAO.txt") $Dist -Force -ErrorAction SilentlyContinue
    $EnvSrc = Join-Path $Root ".env"
    if (Test-Path $EnvSrc) {
        Copy-Item $EnvSrc $Dist -Force
        Write-Host "Copiado .env com suas chaves para dist\Cortex (cuidado ao compartilhar o ZIP)."
    }
    Write-Host ""
    Write-Host "Pronto! Pasta para enviar ao seu amigo:"
    Write-Host "  $Dist"
    Write-Host ""
    Write-Host "Compacte a pasta 'Cortex' em ZIP e envie. Ele só precisa executar Cortex.exe"
} else {
    Write-Host "Falha: dist\Cortex não foi criada." -ForegroundColor Red
    exit 1
}
