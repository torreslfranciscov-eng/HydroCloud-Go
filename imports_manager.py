"""Compatibilidad mínima para MyCloud GOES.

Este proyecto usa un módulo auxiliar llamado imports_manager para generar e importar
archivos .mis. En este workspace no existe dicho archivo, por lo que se implementa
una versión ligera que no rompe la importación ni el arranque del backend Oracle.
"""

from __future__ import annotations

import glob
import os
from typing import Any


def init(*args, **kwargs):
    """Inicialización no-op para compatibilidad con la app principal."""
    return True


def generar_archivo_mis(dcp_id, meta, raw_header, raw_payload, valores, estacion=None, sensores=None):
    """Genera un archivo .mis si la estación lo requiere.

    En esta versión no hace nada y devuelve None.
    """
    return None


def importar_archivo_mis(ruta: str, sensores: Any = None, estaciones: Any = None, **kwargs) -> int:
    """Importa un archivo .mis histórico sin efecto en esta compatibilidad."""
    if not ruta or not os.path.exists(ruta):
        return 0
    return 0


def importardirectorio_mis(ruta: str, sensores: Any = None, estaciones: Any = None, patron: str = "*.mis", **kwargs) -> int:
    """Alias de compatibilidad por typo de nombre."""
    return import_directorio_mis(ruta, sensores=sensores, estaciones=estaciones, patron=patron, **kwargs)


def import_directorio_mis(ruta: str, sensores: Any = None, estaciones: Any = None, patron: str = "*.mis", **kwargs) -> int:
    """Importa todos los archivos .mis de un directorio."""
    if not ruta or not os.path.isdir(ruta):
        return 0

    matches = sorted(glob.glob(os.path.join(ruta, patron)))
    total = 0
    for file_path in matches:
        total += importar_archivo_mis(file_path, sensores=sensores, estaciones=estaciones, **kwargs)
    return total
