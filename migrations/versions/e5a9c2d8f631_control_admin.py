"""Control de accesos y detalle de auditoría; ajustes existentes intactos."""
from alembic import op
import sqlalchemy as sa

revision = 'e5a9c2d8f631'
down_revision = 'd4b8e6a1f725'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('usuarios') as batch:
        batch.add_column(sa.Column('sesion_version', sa.Integer(), nullable=False, server_default='0'))
        batch.add_column(sa.Column('cambiar_password', sa.Boolean(), nullable=False, server_default=sa.false()))
        batch.add_column(sa.Column('anuncios_cerrados', sa.JSON(), nullable=True))
    with op.batch_alter_table('auditoria') as batch:
        batch.add_column(sa.Column('ajuste_clave', sa.String(150), nullable=True))
        batch.add_column(sa.Column('valor_anterior', sa.Text(), nullable=True))
        batch.add_column(sa.Column('valor_nuevo', sa.Text(), nullable=True))


def downgrade():
    with op.batch_alter_table('auditoria') as batch:
        for campo in ('valor_nuevo', 'valor_anterior', 'ajuste_clave'):
            batch.drop_column(campo)
    with op.batch_alter_table('usuarios') as batch:
        for campo in ('anuncios_cerrados', 'cambiar_password', 'sesion_version'):
            batch.drop_column(campo)
