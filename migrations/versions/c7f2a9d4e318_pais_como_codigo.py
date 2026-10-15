"""país del cliente como código ISO (ES, MX…) en vez de texto libre (15/10/2026)

Pasa lo que había escrito a mano («España», «Spain», «Alemania»…) a su código con app/paises.codigo_de.
Lo que no se reconoce se queda tal cual: el formulario del cliente lo enseña marcado «revisar».
La vuelta atrás escribe el nombre en español.

Revision ID: c7f2a9d4e318
Revises: b5e1c7d9a206
Create Date: 2026-10-15 15:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'c7f2a9d4e318'
down_revision = 'b5e1c7d9a206'
branch_labels = None
depends_on = None

clientes = sa.table('clientes', sa.column('id', sa.Integer), sa.column('pais', sa.String),
                    sa.column('envio_pais', sa.String))


def _convertir(funcion):
    conexion = op.get_bind()
    for fila in conexion.execute(sa.select(clientes.c.id, clientes.c.pais, clientes.c.envio_pais)).all():
        nuevos = {}
        for campo in ("pais", "envio_pais"):
            valor = getattr(fila, campo)
            if valor:
                convertido = funcion(valor)
                if convertido and convertido != valor:
                    nuevos[campo] = convertido
        if nuevos:
            conexion.execute(clientes.update().where(clientes.c.id == fila.id).values(**nuevos))


def upgrade():
    from app import paises
    _convertir(paises.codigo_de)


def downgrade():
    from app import paises
    _convertir(lambda v: paises.nombre(v, "es") if paises.es_codigo(v) else None)
