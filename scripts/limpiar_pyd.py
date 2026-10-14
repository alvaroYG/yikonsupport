"""
Borra las extensiones compiladas (.pyd en Windows, .so en Linux) del entorno
virtual SOLO cuando el paquete trae también la versión en Python puro (.py).

¿Para qué? Algunos Windows (Smart App Control / Control de aplicaciones)
bloquean las DLL no firmadas que instala pip. Librerías como SQLAlchemy o
fonttools funcionan igual sin ellas (algo más lentas, inapreciable aquí).

Uso (con el entorno virtual activado):   python scripts/limpiar_pyd.py
Hay que repetirlo después de cada `pip install` o actualización.
"""
import site
import sys
from pathlib import Path

PAQUETES = ["sqlalchemy", "fontTools"]  # añade aquí otros si dan el mismo error


def main():
    dirs = [Path(p) for p in site.getsitepackages()]
    borrados = 0
    for d in dirs:
        for paquete in PAQUETES:
            raiz = d / paquete
            if not raiz.is_dir():
                continue
            for ext in list(raiz.rglob("*.pyd")) + list(raiz.rglob("*.so")):
                puro = ext.with_name(ext.name.split(".")[0] + ".py")
                if puro.exists():
                    ext.unlink()
                    borrados += 1
                    print(f"  borrado {ext.relative_to(d)}")
                else:
                    print(f"  SE QUEDA {ext.relative_to(d)} (no tiene versión .py)")
    print(f"Listo: {borrados} archivos compilados eliminados ({sys.prefix})")


if __name__ == "__main__":
    main()
