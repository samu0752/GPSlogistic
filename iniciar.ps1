param([switch]$CheckOnly)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$env:PYTHONUTF8 = '1'
$venvPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $venvPython)) {
    $gpsPython = $null
    $candidates = @()
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command -and $command.Source -notlike '*\Microsoft\WindowsApps\python.exe') { $candidates += $command.Source }
    $pyLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($pyLauncher) {
        $resolvedPython = & $pyLauncher.Source -3 -c 'import sys;print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0) { $candidates += $resolvedPython }
    }
    $candidates += Get-ChildItem -Path "$env:ProgramFiles\WindowsApps\OpenAI.CodexPrimaryRuntime.*\dependencies\python\python.exe" -ErrorAction SilentlyContinue | Select-Object -ExpandProperty FullName
    foreach ($candidate in $candidates) {
        try {
            & $candidate -c 'import sys;sys.exit(0 if sys.version_info >= (3,11) else 1)' 2>$null
            if ($LASTEXITCODE -eq 0) { $gpsPython = $candidate; break }
        } catch { }
    }
    if (-not $gpsPython) { throw 'Python 3.11 ou superior nao encontrado. Instale Python e execute novamente.' }
    & $gpsPython -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Nao foi possivel criar o ambiente Python.' }
}
& $venvPython -c "import importlib.util,sys;sys.exit(int(importlib.util.find_spec('flask') is None))"
if ($LASTEXITCODE -ne 0) {
    & $venvPython -m pip install -r requirements.txt
    if ($LASTEXITCODE -ne 0) { throw 'Falha ao instalar dependencias. Verifique a conexao com a internet.' }
}
& $venvPython -X utf8 manage.py init --generate-password
if ($LASTEXITCODE -ne 0) { throw 'Inicializacao interrompida. Consulte a mensagem acima.' }
Write-Host 'Acesso: http://127.0.0.1:5050'
Write-Host 'Usuario: samuel. Se o banco foi criado agora, a senha temporaria apareceu acima.'
if ($CheckOnly) { exit 0 }
Write-Host 'Mantenha esta janela aberta. Para encerrar, pressione Ctrl+C.'
& $venvPython -X utf8 run.py --open
