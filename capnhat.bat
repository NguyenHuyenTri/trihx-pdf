@echo off
setlocal
cd /d "%~dp0"

where git >nul 2>nul
if errorlevel 1 (
  echo Chua tim thay Git. Hay cai Git for Windows roi chay lai capnhat.bat.
  pause
  exit /b 1
)

if not exist ".git" (
  echo Thu muc nay chua duoc clone tu GitHub.
  echo Hay clone repo GitHub truoc, sau do chay capnhat.bat trong thu muc du an.
  pause
  exit /b 1
)

git pull --ff-only
if errorlevel 1 (
  echo Khong cap nhat duoc ma nguon. Kiem tra ket noi GitHub va cac thay doi cuc bo.
  pause
  exit /b 1
)

where python >nul 2>nul
if errorlevel 1 (
  echo Chua tim thay Python. Hay cai Python roi mo lai capnhat.bat.
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" python -m venv .venv
if errorlevel 1 (
  echo Khong tao duoc moi truong Python .venv.
  pause
  exit /b 1
)

call ".venv\Scripts\activate.bat"
python -m pip install -r requirements.txt pyinstaller
if errorlevel 1 (
  echo Cai thu vien that bai.
  pause
  exit /b 1
)

python -m PyInstaller --clean --noconfirm PDFReader.spec
if errorlevel 1 (
  echo Tao HX PDF.exe that bai.
  pause
  exit /b 1
)

echo Da cap nhat xong: dist\HX PDF.exe
pause
