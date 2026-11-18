# MiniFloat

MiniFloat es una aplicación de escritorio para Windows construida con Python y
PySide6. La ventana flotante permite trabajar sobre otras aplicaciones sin
ocupar toda la pantalla. El escritorio contiene dos ventanas de prueba
provisionales; no son herramientas reales ni se guarda su distribución.

## Instalación y ejecución

Se ha probado con Windows, Python 3.15.2 y PySide6 6.12.0. Desde PowerShell,
en la carpeta del proyecto:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python main.py
```

En Windows, comprueba el movimiento, el redimensionado, la superposición,
la minimización y el cierre de la ventana.

## Ventana y configuración

- Arrastra la barra de título para mover la ventana y sus bordes o esquinas para
  redimensionarla.
- Los botones permiten minimizar o cerrar. No se incluye maximización porque
  MiniFloat está pensado como una ventana flotante compacta.
- El deslizador de la barra superior ajusta la opacidad de toda la ventana,
  incluidos controles y ventanas internas, entre el 25 % y el 100 %. Al 100 %
  el fondo es opaco; las esquinas siguen siendo transparentes.
- La configuración se crea en `%LOCALAPPDATA%\MiniFloat\settings.json`:

  ```json
  {
      "window": {
          "always_on_top": true,
          "opacity": 0.92
      }
  }
  ```

- Con MiniFloat cerrada, edita `always_on_top` (`true` o `false`) y la opacidad
  inicial `opacity` (entre `0.60` y `1.00`). Los cambios se aplican al iniciar.
  El deslizador no guarda aún sus cambios: al volver a abrir se utiliza el
  valor del archivo.
- Si el archivo es ilegible, corrupto o tiene valores inválidos, MiniFloat
  muestra un error y no lo sobrescribe. Corrígelo antes de volver a iniciar.
- La posición y el tamaño todavía no se guardan al cerrar.

## Prototipo de escritorio

Las dos ventanas de prueba pueden moverse, redimensionarse, superponerse,
minimizarse y cerrarse por separado. Su contenido y su distribución se
reinician al abrir MiniFloat; todavía no hay catálogo para volver a abrirlas.
Si el escritorio queda demasiado pequeño, las barras de desplazamiento permiten
acceder a las partes que queden fuera. Comprueba también el comportamiento al
mover una ventana cerca de los bordes y al reducir MiniFloat.

Se utiliza `QMdiArea` como prueba, no como decisión visual definitiva: sus
decoraciones y controles dependen del estilo de Qt y pueden tener apariencia
MDI clásica. Las ventanas internas están contenidas en MiniFloat: no son
ventanas independientes de Windows ni se intercalan con aplicaciones externas.
MiniFloat es una ventana flotante sobre el escritorio de Windows, no un
escritorio virtual de Windows ni un sustituto de este. La configuración de la
sección anterior también sigue pendiente de validación completa en Windows.

## Pruebas

```powershell
python -m unittest discover -s tests -v
python -m compileall -q main.py app ui tests
```
