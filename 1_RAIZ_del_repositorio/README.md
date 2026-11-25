# Live2Pro (v0.1 — SIN PROBAR en Windows)

Estado honesto: el código compila (sintaxis verificada) y la validación de URL fue probada.
NO fue probado contra YouTube real, NDI real, libVLC real ni ProPresenter real.
No hay .exe: se genera en Windows con `build.bat`.

## Hallazgos de la investigación (fuentes: soporte oficial de Renewed Vision)
- "Video Stream" por URL (HLS .m3u8) está documentado desde **ProPresenter 22**. No figura para 21.
- El artículo dice que las URL de YouTube NO funcionan directamente (solo .m3u8 HTTPS). Además pide HTTPS; un HLS local es HTTP (sin probar).
- NDI como entrada de video sí está documentado (Ajustes > Entradas, "NDI Input Discovery").
- La Biblioteca de medios acepta archivos; no hay documentación de que acepte arrastrar un stream/.m3u8/.url.

## Arquitectura elegida
- yt-dlp.exe (subproceso, actualizable con el botón) -> manifiesto HLS de YouTube.
- Vista previa: libVLC embebido (muda).
- Salida A (PP 21): ffmpeg -> cámara virtual Unity Capture (pyvirtualcam) + audio a la PC (sounddevice).
- Salida B (PP 22+): ffmpeg -c copy -> HLS local http://127.0.0.1:38765/live.m3u8.
- Reconexión automática y re-resolución de URL (caduca ~6 h).

## Compilar (Windows 11 x64)
1. Instalar Python 3.11/3.12 64-bit (solo en la PC de desarrollo).
2. Crear `bin\` con ffmpeg.exe, yt-dlp.exe, deno.exe y `vlc\` con libvlc.dll, libvlccore.dll y plugins\ (VLC 3.x 64-bit).
3. Ejecutar `build.bat` -> `dist\Live2Pro\Live2Pro.exe` (portátil).
4. Opcional: compilar `installer.iss` con Inno Setup.
5. En la PC del usuario instalar NDI Tools (runtime de NDI) si usará modo NDI.

## Uso con ProPresenter 21 — Opción 1: NDI (recomendada; instalar NDI Tools)
1. Instalar NDI Tools (ndi.video) y reiniciar la PC.
2. Live2Pro: URL > CONECTAR > NDI > GENERAR RECURSO.
3. ProPresenter > Ajustes > Entradas > Video Inputs > + > Dispositivo: "LIVE2PRO - ...". El audio viaja dentro de NDI.

## Uso con ProPresenter 21 — Opción 2: cámara virtual (sin NDI)
Requisito único: registrar la cámara virtual Unity Capture (el instalador lo hace solo;
en la versión portátil ejecutar driver\Install.bat como administrador).
1. Live2Pro: pegar URL > CONECTAR > "Cámara virtual" > GENERAR RECURSO.
2. ProPresenter > Ajustes > Entradas > Video Inputs > "+" > Dispositivo: "Unity Video Capture".
3. El audio sale por la salida de sonido de la PC elegida en Live2Pro (no pasa por ProPresenter).
   Si el video va adelantado respecto del audio, subir "ms retardo de video".

## Uso con ProPresenter 22+ (modo HLS local) — EXPERIMENTAL
Copiar la ubicación (http://127.0.0.1:38765/live.m3u8) en Add Media Action > Video Stream.
Si PP rechaza HTTP, ver Limitaciones.

## Pruebas pendientes (obligatorias antes de usarlo en servicio)
1. yt-dlp resuelve un vivo real (¿hace falta deno.exe?).
2. Vista previa libVLC dentro del widget.
3. Cámara virtual: aparece en PP 21; audio sincronizado 10+ min; CPU a 720p/1080p.
4. HLS local: ¿PP 22 valida http://127.0.0.1?
5. ¿PP 21/22 acepta arrastrar el .m3u8 a la Biblioteca de medios? (el elemento arrastrable es un experimento)
6. Reconexión: cortar internet 30 s y verificar.
