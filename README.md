# MiniFloat

MiniFloat es una capa flotante para Windows construida con Python y PySide6.
Permite seleccionar algunas ventanas reales ya abiertas y alojarlas en un
espacio de trabajo de MiniFloat. No recrea esas aplicaciones ni las lanza.

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
- El deslizador de la barra inferior ajusta la opacidad de la ventana principal
  entre el 25 % y el 100 %. Las ventanas externas pueden permanecer opacas.
- La interfaz usa azul grisáceo en el workspace, barras azul grisáceo oscuro,
  lavanda apagado en botones y selección, y un tono intermedio para hover.
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
- El PIN comienza activado. Con **PIN OFF**, MiniFloat bloquea su interacción;
  únicamente el botón PIN permanece accesible. Las ventanas externas se
  deshabilitan mientras dura ese estado. El paso de clics a través de HWND
  externos embebidos depende de la aplicación y no está garantizado. PIN
  controla la entrada; es independiente de Always on Top.
- Si el archivo es ilegible, corrupto o tiene valores inválidos, MiniFloat
  muestra un error y no lo sobrescribe. Corrígelo antes de volver a iniciar.
- La posición y el tamaño todavía no se guardan al cerrar.

## Ventanas externas

Pulsa **+** para enumerar ventanas visibles con título de otros procesos. El
selector muestra el proceso y el título de cada ventana para distinguir varias
ventanas de una misma aplicación. Al añadirla, ocupa el área útil del escritorio
y se adapta al redimensionar MiniFloat. El menú de ventanas externas permite
cambiar la instancia visible, minimizarla/restaurarla o liberarla. Al liberarla,
MiniFloat intenta devolverla a su ventana padre, estilos, geometría y estado
originales. Si la aplicación se cierra por su cuenta, MiniFloat elimina la
instancia de su escritorio.

La integración es específica de Windows. MiniFloat guarda primero el estado
Win32 original de cada HWND y lo reparenta a un host QWidget nativo dentro del
workspace, sin MDI ni contenedores Qt de ventanas foráneas. Win32 es la única
capa que cambia parent, estilos y geometría: al redimensionar MiniFloat,
`SetWindowPos` ajusta la ventana al workspace; al liberarla se restauran
parent/owner, estilos, geometría, estado, visibilidad y habilitación, y se
verifica la restauración antes de eliminar el host. La prueba real de Chrome
mostró que combinar el reparentado de `createWindowContainer()` con mutaciones
directas del mismo HWND provocaba discrepancias de estado y errores Win32 al
restaurarlo; por ello esa ruta Qt no se utiliza. La barra y el botón PIN siguen
el estado Always on Top de MiniFloat, mientras que se elimina `WS_EX_TOPMOST`
de la ventana adoptada para que no compita con esos controles. Las ventanas
cerradas externamente se eliminan sin intentar restaurar un HWND destruido.

El ciclo de adopción y liberación tiene estados explícitos y realiza rollback
si una llamada Win32 falla. Si también falla el rollback, la ventana queda
marcada para recuperación y MiniFloat conserva su host para permitir otro
intento de liberación. Las instancias se administran independientemente; el
menú permite cambiar la ventana que ocupa el área completa, minimizarla o
liberarla. No se lanzan aplicaciones ni se instala código en sus procesos.

La compatibilidad no es universal. Qt documenta que el foco delegado depende
de la plataforma. `SetParent` exige coordinar los estilos Win32 y puede causar
efectos DPI al cruzar procesos con modos DPI distintos. Una aplicación externa
puede no tolerar que su ventana principal se reparentee; además, permisos
elevados distintos entre procesos, ventanas aceleradas por DirectX/Vulkan,
juegos, pantalla completa exclusiva y anti-cheat requieren pruebas individuales.
La opacidad global de MiniFloat no se garantiza sobre el contenido externo.

## Comprobaciones manuales en Windows

1. Añade Notepad; comprueba que ocupa el escritorio, redimensiona MiniFloat,
   libera Notepad y verifica que vuelve a moverse, redimensionarse y cerrarse
   normalmente.
2. Repite el ciclo con Chrome: espera una página real, prueba clic, escritura,
   scroll y cambio de pestaña, y confirma que la barra queda por encima al
   enfocar Chrome y redimensionar MiniFloat.
3. Prueba PIN OFF/ON sobre ventanas añadidas. Verifica específicamente el
   click-through, ya que el HWND hijo puede interceptarlo.
4. Cambia la opacidad con una ventana externa; el contenido puede permanecer
   opaco aunque el marco de MiniFloat cambie.
5. Si está disponible, prueba el juego en ventana. No se garantiza
   compatibilidad con pantalla completa exclusiva ni anti-cheat.

## Pruebas

```powershell
python -m unittest discover -s tests -v
python -m compileall -q main.py app ui tests
```

Referencias técnicas: [Win32 SetParent](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setparent),
[SetWindowPlacement](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowplacement),
[GetWindowPlacement](https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-getwindowplacement)
y [Qt native widgets](https://doc.qt.io/qtforpython-6/PySide6/QtWidgets/QWidget.html#PySide6.QtWidgets.QWidget.winId).
