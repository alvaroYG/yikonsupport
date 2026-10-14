"""
Carga de datos desde la plantilla Excel: productos, kits (con sus componentes) y empresas cliente.
Se usa desde la terminal:  flask importar-datos plantilla.xlsx  [--guardar]

- Sin --guardar es una PRUEBA: lo comprueba todo y dice qué crearía, pero no guarda nada.
- Solo CREA. Lo que ya está en la plataforma (misma referencia, CIF, nombre o prefijo) no se toca:
  se avisa y se sigue con lo demás. Para cambiar algo que ya existe, se hace desde la web.
- Si hay algún ERROR (falta un dato obligatorio, una referencia repetida, un kit con un producto
  que no existe…) no se guarda NADA, aunque se haya pedido --guardar: se arregla el Excel y se repite.
- Cada cosa creada queda en la auditoría («importado de <archivo>»).

Las hojas y sus columnas son las de la plantilla (deploy/plantilla_carga.xlsx). Se reconocen por el
principio del título de la columna, sin importar mayúsculas, tildes ni el asterisco; las columnas que
no se conocen (Notas…) se ignoran, y una hoja que no está se salta.
"""
import os
import re
import unicodedata
from decimal import Decimal, InvalidOperation

from app.extensions import db
from app.models import Cliente, ComponenteKit, Kit, Pedido, Producto, User, prefijo_desde_nombre

IVAS = {Decimal("21"), Decimal("10"), Decimal("4"), Decimal("0")}
REGIMENES = {"espana": "es", "es": "es", "ue": "ue", "exportacion": "export", "export": "export"}

# hoja → [(campo, principios posibles del título de la columna)]
COLUMNAS = {
    "Productos": [("referencia", ["referencia"]), ("nombre", ["nombre"]), ("marca", ["marca", "categoria"]),
                  ("precio", ["precio"]), ("iva", ["iva"]), ("stock_minimo", ["stock minimo"]),
                  ("controlar_stock", ["controlar stock"]), ("activo", ["activo"])],
    "Kits": [("referencia", ["referencia"]), ("nombre", ["nombre"]), ("descripcion", ["descripcion"]),
             ("precio", ["precio"]), ("iva", ["iva"]), ("tipo", ["tipo"]), ("activo", ["activo"])],
    "Componentes": [("kit", ["referencia kit", "kit"]), ("producto", ["referencia producto", "producto"]),
                    ("cantidad", ["cantidad"])],
    "Empresas": [("nombre", ["nombre"]), ("razon_social", ["razon social"]), ("cif", ["cif"]),
                 ("prefijo", ["prefijo"]), ("email", ["email"]), ("telefono", ["telefono"]),
                 ("direccion", ["direccion"]), ("ciudad", ["ciudad"]), ("persona_contacto", ["persona de contacto"]),
                 ("regimen_iva", ["iva"]), ("formato_factura", ["formato"]), ("gastos_envio", ["gastos"]),
                 ("ver_precios", ["ve precios"]), ("revisar_facturas", ["revisar facturas"]),
                 ("soporte", ["soporte de cliente"]), ("notas", ["notas"])],
}


def _sin_tildes(texto):
    return unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode().lower()


class DatoMal(ValueError):
    """Un valor de una celda que no se entiende (el mensaje dice cuál y por qué)."""


class Informe:
    def __init__(self):
        self.errores, self.avisos = [], []
        self.creados = {"Productos": 0, "Kits": 0, "Componentes": 0, "Empresas": 0}
        self.existentes = {"Productos": 0, "Kits": 0, "Empresas": 0}
        self.sin_precio = {"Productos": 0, "Kits": 0}

    def error(self, hoja, fila, texto):
        self.errores.append(f"{hoja}, fila {fila}: {texto}")

    def aviso(self, hoja, fila, texto):
        self.avisos.append(f"{hoja}, fila {fila}: {texto}")


def _filas(ws, hoja):
    """(nº de fila, {campo: valor}) de cada fila con algo, según los títulos de la fila 1."""
    filas = ws.iter_rows(values_only=True)
    titulos = [_sin_tildes(t or "").replace("*", "").strip() for t in next(filas, [])]
    columna = {}
    for campo, principios in COLUMNAS[hoja]:
        for i, titulo in enumerate(titulos):
            if i not in columna.values() and any(titulo.startswith(p) for p in principios):
                columna[campo] = i
                break
    for n, valores in enumerate(filas, start=2):
        datos = {campo: valores[i] if i < len(valores) else None for campo, i in columna.items()}
        datos = {c: (v.strip() if isinstance(v, str) else v) for c, v in datos.items()}
        datos = {c: (None if v == "" else v) for c, v in datos.items()}
        if any(v is not None for v in datos.values()):
            yield n, datos


# --- lectura de valores ------------------------------------------------------------------------

def _texto(v, largo, nombre):
    if v is None:
        return None
    v = str(int(v)) if isinstance(v, float) and v.is_integer() else str(v).strip()
    if len(v) > largo:
        raise DatoMal(f"«{nombre}» es demasiado largo (máx. {largo} caracteres)")
    return v or None


def _decimal(v, nombre):
    if v is None:
        return None
    try:
        d = Decimal(str(v).replace("€", "").replace(" ", "").replace(",", ".")) if not isinstance(v, (int, float)) \
            else Decimal(str(v))
    except InvalidOperation:
        raise DatoMal(f"«{nombre}» no es un número: {v}")
    if d < 0:
        raise DatoMal(f"«{nombre}» no puede ser negativo")
    return d.quantize(Decimal("0.01"))


def _iva(v):
    if v is None:
        return Decimal("21.00")
    d = _decimal(str(v).replace("%", ""), "IVA")
    if Decimal("0") < d < Decimal("1"):          # 0,21 (celda con formato de porcentaje)
        d *= 100
    if d.quantize(Decimal("1")) not in IVAS or d != d.quantize(Decimal("1")):
        raise DatoMal(f"IVA {v}: tiene que ser 21, 10, 4 o 0")
    return d.quantize(Decimal("0.01"))


def _entero(v, nombre, minimo=0):
    if v is None:
        return None
    try:
        n = int(Decimal(str(v).replace(",", ".")))
        if Decimal(str(v).replace(",", ".")) != n:
            raise InvalidOperation
    except InvalidOperation:
        raise DatoMal(f"«{nombre}» tiene que ser un número entero: {v}")
    if n < minimo:
        raise DatoMal(f"«{nombre}» tiene que ser {minimo} o más")
    return n


def _si_no(v, nombre, defecto):
    if v is None:
        return defecto
    t = _sin_tildes(v).strip()
    if t in ("si", "s", "x", "1", "true", "yes"):
        return True
    if t in ("no", "n", "0", "false"):
        return False
    raise DatoMal(f"«{nombre}» tiene que ser Sí o No: {v}")


# --- cada hoja ---------------------------------------------------------------------------------

def _productos(ws, informe, origen):
    nuevos = {}
    for n, d in _filas(ws, "Productos"):
        try:
            ref = _texto(d.get("referencia"), 50, "Referencia")
            nombre = _texto(d.get("nombre"), 200, "Nombre")
            if not ref or not nombre:
                raise DatoMal("faltan la referencia o el nombre (obligatorios)")
            if ref.lower() in nuevos:
                raise DatoMal(f"la referencia {ref} está repetida en la hoja (fila {nuevos[ref.lower()][0]})")
            precio = _decimal(d.get("precio"), "Precio")
            datos = dict(referencia=ref, nombre=nombre, categoria=_texto(d.get("marca"), 80, "Marca"),
                         precio=precio or Decimal("0.00"), iva_pct=_iva(d.get("iva")),
                         stock_minimo=_entero(d.get("stock_minimo"), "Stock mínimo") or 0,
                         controlar_stock=_si_no(d.get("controlar_stock"), "Controlar stock", True),
                         activo=_si_no(d.get("activo"), "Activo", True))
        except DatoMal as e:
            informe.error("Productos", n, str(e))
            continue
        nuevos[ref.lower()] = (n, None)
        if db.session.scalar(db.select(Producto).where(db.func.lower(Producto.referencia) == ref.lower())):
            informe.existentes["Productos"] += 1
            informe.aviso("Productos", n, f"{ref} ya existe: no se toca")
            continue
        producto = Producto(**datos)
        db.session.add(producto)
        db.session.flush()
        _auditoria(producto, f"{ref} · importado de {origen}")
        nuevos[ref.lower()] = (n, producto)
        informe.creados["Productos"] += 1
        informe.sin_precio["Productos"] += precio is None or precio == 0


def _kits(ws, informe, origen):
    """Devuelve {referencia en minúsculas: Kit nuevo (o None si ya existía)}."""
    kits = {}
    for n, d in _filas(ws, "Kits"):
        try:
            ref = _texto(d.get("referencia"), 50, "Referencia kit")
            nombre = _texto(d.get("nombre"), 200, "Nombre")
            if not ref or not nombre:
                raise DatoMal("faltan la referencia o el nombre del kit (obligatorios)")
            if ref.lower() in kits:
                raise DatoMal(f"el kit {ref} está repetido en la hoja")
            tipo = _sin_tildes(d.get("tipo") or "").strip()
            if tipo not in ("montado", "cerrado"):
                raise DatoMal("«Tipo» tiene que ser Montado o Cerrado")
            precio = _decimal(d.get("precio"), "Precio")
            datos = dict(referencia=ref, nombre=nombre, descripcion=_texto(d.get("descripcion"), 5000, "Descripción"),
                         precio=precio or Decimal("0.00"), iva_pct=_iva(d.get("iva")), cerrado=tipo == "cerrado",
                         activo=_si_no(d.get("activo"), "Activo", True))
        except DatoMal as e:
            informe.error("Kits", n, str(e))
            continue
        if db.session.scalar(db.select(Kit).where(db.func.lower(Kit.referencia) == ref.lower())):
            informe.existentes["Kits"] += 1
            informe.aviso("Kits", n, f"{ref} ya existe: no se toca (ni sus componentes)")
            kits[ref.lower()] = None
            continue
        kit = Kit(**datos)
        db.session.add(kit)
        db.session.flush()
        kits[ref.lower()] = kit
        informe.creados["Kits"] += 1
        informe.sin_precio["Kits"] += precio is None or precio == 0
    return kits


def _componentes(ws, informe, kits, origen):
    vistos = {}
    for n, d in _filas(ws, "Componentes"):
        try:
            ref_kit = _texto(d.get("kit"), 50, "Referencia kit")
            ref_prod = _texto(d.get("producto"), 50, "Referencia producto")
            cantidad = _entero(d.get("cantidad"), "Cantidad", minimo=1)
            if not ref_kit or not ref_prod or cantidad is None:
                raise DatoMal("faltan el kit, el producto o la cantidad (obligatorios)")
            if ref_kit.lower() not in kits:
                raise DatoMal(f"el kit {ref_kit} no está en la hoja «Kits»")
            producto = db.session.scalar(db.select(Producto).where(db.func.lower(Producto.referencia) == ref_prod.lower()))
            if producto is None:
                raise DatoMal(f"el producto {ref_prod} no está en «Productos» ni en la plataforma")
            clave = (ref_kit.lower(), producto.id)
            if clave in vistos:
                raise DatoMal(f"{ref_prod} ya está en el kit {ref_kit} (fila {vistos[clave]}): junta las cantidades")
            vistos[clave] = n
        except DatoMal as e:
            informe.error("Componentes", n, str(e))
            continue
        kit = kits[ref_kit.lower()]
        if kit is None:                       # el kit ya existía: no se toca
            continue
        kit.componentes.append(ComponenteKit(producto=producto, cantidad=cantidad, orden=len(kit.componentes)))
        informe.creados["Componentes"] += 1
    for ref, kit in kits.items():
        if kit is None:
            continue
        if not kit.componentes:
            informe.error("Kits", "-", f"el kit {kit.referencia} no tiene ningún producto en «Componentes»")
        db.session.flush()
        _auditoria(kit, f"{kit.referencia} · {len(kit.componentes)} productos · importado de {origen}")


def _prefijo_libre(prefijo, ya):
    p = prefijo.lower()
    if p in ya or db.session.scalar(db.select(Cliente.id).where(db.func.lower(Cliente.prefijo) == p)):
        return False
    referencia = db.func.lower(Pedido.referencia_interna)
    return not db.session.scalar(db.select(Pedido.id).where(db.or_(
        referencia.like(p + "\\_%", escape="\\"), referencia.like(f"yk-____-{p}-%"))).limit(1))


def _empresas(ws, informe, origen):
    prefijos, cifs, nombres = set(), {}, {}
    for n, d in _filas(ws, "Empresas"):
        try:
            nombre = _texto(d.get("nombre"), 150, "Nombre")
            if not nombre:
                raise DatoMal("falta el nombre (obligatorio)")
            if nombre.lower() in nombres:
                raise DatoMal(f"«{nombre}» está repetida en la hoja (fila {nombres[nombre.lower()]})")
            nombres[nombre.lower()] = n
            cif = _texto(d.get("cif"), 20, "CIF")
            cif = cif.upper().replace("-", "").replace(" ", "") if cif else None
            if cif and cif in cifs:
                raise DatoMal(f"el CIF {cif} está repetido en la hoja (fila {cifs[cif]})")
            if cif:
                cifs[cif] = n
            ya = db.session.scalar(db.select(Cliente).where(
                db.or_(db.func.lower(Cliente.nombre) == nombre.lower(), Cliente.cif == cif) if cif
                else db.func.lower(Cliente.nombre) == nombre.lower()))
            if ya:
                informe.existentes["Empresas"] += 1
                informe.aviso("Empresas", n, f"«{nombre}» ya existe (como «{ya.nombre}»): no se toca")
                continue
            prefijo = _texto(d.get("prefijo"), 10, "Prefijo")
            generado = prefijo is None
            prefijo = prefijo or prefijo_desde_nombre(nombre)
            if not re.fullmatch(r"[A-Za-z0-9]{2,10}", prefijo):
                raise DatoMal(f"prefijo «{prefijo}»: de 2 a 10 letras o números, sin espacios ni tildes")
            if not _prefijo_libre(prefijo, prefijos):
                raise DatoMal(f"el prefijo «{prefijo}» ya lo usa otra empresa"
                              + (" (sale del nombre: escribe uno en la columna Prefijo)" if generado else ""))
            prefijos.add(prefijo.lower())
            regimen = None
            if d.get("regimen_iva"):
                regimen = REGIMENES.get(_sin_tildes(d["regimen_iva"]).strip())
                if regimen is None:
                    raise DatoMal(f"IVA «{d['regimen_iva']}»: tiene que ser España, UE o Exportación")
            formato = _texto(d.get("formato_factura"), 1, "Formato de factura")
            if formato and formato.upper() not in ("A", "B", "C"):
                raise DatoMal("«Formato de factura» tiene que ser A, B o C")
            email = _texto(d.get("email"), 120, "Email")
            if email and not re.fullmatch(r"[^@\s,;]+@[^@\s,;]+\.[^@\s,;]+", email):
                raise DatoMal(f"el email «{email}» no parece válido (uno solo por empresa)")
            soporte = []
            for e in re.split(r"[,;\s]+", d.get("soporte") or ""):
                if not e:
                    continue
                u = db.session.scalar(db.select(User).where(db.func.lower(User.email) == e.lower()))
                if u is None or u.rol != "fas":
                    raise DatoMal(f"«{e}» no es un usuario de Soporte de cliente de la plataforma")
                soporte.append(u)
            cliente = Cliente(
                nombre=nombre, razon_social=_texto(d.get("razon_social"), 200, "Razón social"), cif=cif,
                prefijo=prefijo, email=email.lower() if email else None, telefono=_texto(d.get("telefono"), 30, "Teléfono"),
                direccion=_texto(d.get("direccion"), 250, "Dirección"), ciudad=_texto(d.get("ciudad"), 100, "Ciudad"),
                persona_contacto=_texto(d.get("persona_contacto"), 120, "Persona de contacto"),
                notas=_texto(d.get("notas"), 5000, "Notas"), regimen_iva=regimen,
                formato_factura=formato.upper() if formato else None,
                gastos_envio=_decimal(d.get("gastos_envio"), "Gastos de envío"),
                ver_precios=_si_no(d.get("ver_precios"), "Ve precios", False),
                revisar_facturas=_si_no(d.get("revisar_facturas"), "Revisar facturas", False))
        except DatoMal as e:
            informe.error("Empresas", n, str(e))
            continue
        cliente.logisticos = soporte
        db.session.add(cliente)
        db.session.flush()
        _auditoria(cliente, f"{nombre} · prefijo {prefijo} · importado de {origen}")
        informe.creados["Empresas"] += 1
        if generado:
            informe.aviso("Empresas", n, f"«{nombre}»: prefijo {prefijo} (sacado del nombre)")


def _auditoria(objeto, detalle):
    from app.auditoria import registrar
    registrar("crear", objeto, detalle)


def importar(ruta, guardar=False):
    """Lee la plantilla y lo deja todo en la sesión. Guarda (commit) solo si se pide y no hay
    errores; si no, deshace (rollback). Devuelve el Informe."""
    from openpyxl import load_workbook
    informe = Informe()
    try:
        libro = load_workbook(ruta, read_only=True, data_only=True)
    except Exception as e:                       # no existe, no es un Excel…
        informe.errores.append(f"No se puede abrir {ruta}: {e}")
        return informe
    origen = os.path.basename(ruta)
    hojas = {_sin_tildes(h).strip(): h for h in libro.sheetnames}
    try:
        if "productos" in hojas:
            _productos(libro[hojas["productos"]], informe, origen)
        kits = _kits(libro[hojas["kits"]], informe, origen) if "kits" in hojas else {}
        if "componentes" in hojas:
            _componentes(libro[hojas["componentes"]], informe, kits, origen)
        elif any(k is not None for k in kits.values()):
            informe.errores.append("Hay kits nuevos pero falta la hoja «Componentes»")
        if "empresas" in hojas:
            _empresas(libro[hojas["empresas"]], informe, origen)
        if not any(h in hojas for h in ("productos", "kits", "empresas")):
            informe.errores.append("El Excel no tiene ninguna hoja «Productos», «Kits» ni «Empresas»")
    except Exception:
        db.session.rollback()
        raise
    finally:
        libro.close()
    if guardar and not informe.errores:
        db.session.commit()
    else:
        db.session.rollback()
    return informe
