@echo off
REM Compila Live2Pro en una carpeta portátil (onedir = arranque rápido).
REM Requisitos previos en ESTA carpeta:
REM   bin\ffmpeg.exe  bin\yt-dlp.exe  bin\deno.exe   (descargar de sus sitios oficiales)
REM   vlc\            (copiar libvlc.dll, libvlccore.dll y la carpeta plugins\ de VLC 3.x de 64 bits)
python -m venv .venv || exit /b 1
call .venv\Scripts\activate
pip install -r requirements.txt || exit /b 1
pyinstaller --noconfirm --windowed --name Live2Pro --paths live2pro ^
  --collect-all NDIlib --collect-all PySide6 --hidden-import vlc ^
  live2pro\app.py || exit /b 1
xcopy /E /I /Y bin  dist\Live2Pro\bin
xcopy /E /I /Y vlc  dist\Live2Pro\vlc
echo.
echo Listo: dist\Live2Pro\Live2Pro.exe
echo Para el instalador: abrir installer.iss con Inno Setup y compilar.
