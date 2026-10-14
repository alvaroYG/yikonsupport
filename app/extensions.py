from flask_babel import Babel, lazy_gettext as _l
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import CSRFProtect
from sqlalchemy import MetaData

# Nombres fijos para índices y claves: sin esto, SQLite no puede
# modificar o borrar restricciones en migraciones futuras.
convencion = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
db = SQLAlchemy(metadata=MetaData(naming_convention=convencion))
migrate = Migrate()
csrf = CSRFProtect()
babel = Babel()

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message = _l("Inicia sesión para acceder a esta página.")
login_manager.login_message_category = "info"
