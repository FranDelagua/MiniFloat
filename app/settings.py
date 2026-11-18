import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


class SettingsError(Exception):
    """The settings file could not be read, validated, or saved."""


@dataclass(frozen=True)
class WindowSettings:
    always_on_top: bool = True
    opacity: float = 0.92


def settings_path() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA")
    if not local_app_data:
        raise SettingsError("La variable LOCALAPPDATA no está definida.")
    return Path(local_app_data) / "MiniFloat" / "settings.json"


def load_settings(path: Path) -> WindowSettings:
    try:
        if path.exists():
            with path.open("r", encoding="utf-8") as file:
                data = json.load(file)
        else:
            data = {}
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise SettingsError(f"No se pudo leer la configuración en {path}: {error}") from error

    if not isinstance(data, dict):
        raise SettingsError(f"La configuración en {path} debe ser un objeto JSON.")
    window = data.get("window", {})
    if not isinstance(window, dict):
        raise SettingsError("La sección window debe ser un objeto JSON.")

    defaults = WindowSettings()
    always_on_top = window.get("always_on_top", defaults.always_on_top)
    opacity = window.get("opacity", defaults.opacity)
    if not isinstance(always_on_top, bool):
        raise SettingsError("window.always_on_top debe ser true o false.")
    if (
        isinstance(opacity, bool)
        or not isinstance(opacity, (int, float))
        or not 0.60 <= opacity <= 1.00
    ):
        raise SettingsError("window.opacity debe ser un número entre 0.60 y 1.00.")

    settings = WindowSettings(always_on_top=always_on_top, opacity=float(opacity))
    if "window" not in data or "always_on_top" not in window or "opacity" not in window:
        window["always_on_top"] = settings.always_on_top
        window["opacity"] = settings.opacity
        data["window"] = window
        _write_settings(path, data)
    return settings


def _write_settings(path: Path, data: dict) -> None:
    temporary_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, delete=False
        ) as file:
            temporary_path = Path(file.name)
            json.dump(data, file, ensure_ascii=False, indent=4, allow_nan=False)
            file.write("\n")
        os.replace(temporary_path, path)
    except (OSError, ValueError) as error:
        raise SettingsError(f"No se pudo guardar la configuración en {path}: {error}") from error
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink()
