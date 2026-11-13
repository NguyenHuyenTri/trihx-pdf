$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$tempRoot = Join-Path $env:TEMP ("hxp-update-" + [guid]::NewGuid().ToString("N"))
$archivePath = Join-Path $tempRoot "source.zip"

try {
    $runningApp = Get-Process -Name "HX PDF" -ErrorAction SilentlyContinue
    if ($runningApp) {
        throw "HX PDF dang mo. Hay dong tat ca cua so HX PDF roi chay lai capnhat.bat."
    }

    New-Item -ItemType Directory -Path $tempRoot | Out-Null
    $archiveUrl = "https://codeload.github.com/NguyenHuyenTri/trihx-pdf/zip/refs/heads/main"
    Write-Host "Dang tai ma nguon HX PDF moi nhat..."
    Invoke-WebRequest -Uri $archiveUrl -OutFile $archivePath -UseBasicParsing
    Expand-Archive -LiteralPath $archivePath -DestinationPath $tempRoot -Force

    $sourceRoot = Join-Path $tempRoot "trihx-pdf-main"
    if (-not (Test-Path (Join-Path $sourceRoot "main.py"))) {
        throw "Khong tim thay ma nguon trong goi tai ve."
    }

    Get-ChildItem -LiteralPath $sourceRoot -Force | Where-Object {
        $_.Name -notin @("capnhat.bat", "capnhat.ps1")
    } | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $projectRoot -Recurse -Force
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if (-not $python) {
        throw "Chua tim thay Python. Hay cai Python, sau do chay lai capnhat.bat."
    }

    $venvPath = Join-Path $projectRoot ".venv"
    $venvPython = Join-Path $venvPath "Scripts\python.exe"
    if (-not (Test-Path $venvPython)) {
        Write-Host "Dang tao moi truong Python..."
        & $python.Source -m venv $venvPath
        if ($LASTEXITCODE -ne 0) { throw "Khong tao duoc moi truong Python." }
    }

    Write-Host "Dang cai thu vien va tao HX PDF.exe..."
    & $venvPython -m pip install --disable-pip-version-check -r (Join-Path $projectRoot "requirements.txt") pyinstaller
    if ($LASTEXITCODE -ne 0) { throw "Cai thu vien that bai." }

    & $venvPython -m PyInstaller --clean --noconfirm (Join-Path $projectRoot "PDFReader.spec")
    if ($LASTEXITCODE -ne 0) { throw "Tao HX PDF.exe that bai." }

    Copy-Item -LiteralPath (Join-Path $sourceRoot "capnhat.bat") -Destination $projectRoot -Force
    Copy-Item -LiteralPath (Join-Path $sourceRoot "capnhat.ps1") -Destination $projectRoot -Force
    Write-Host "Cap nhat xong: dist\HX PDF.exe"
}
catch {
    Write-Host "LOI: $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
finally {
    if (Test-Path $tempRoot) {
        Remove-Item -LiteralPath $tempRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}
