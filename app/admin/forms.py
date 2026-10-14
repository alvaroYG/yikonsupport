from flask_wtf import FlaskForm
from flask_babel import gettext as _, lazy_gettext as _l
from wtforms import BooleanField, PasswordField, SelectField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, Length, Optional, ValidationError

from app.extensions import db
from app.models import Cliente, User
from app.permisos import (ROLES, ROLES_CLIENTE, chromgo_para_clientes, documentos_activos, roles_disponibles,
                          soporte_activo)


class UsuarioForm(FlaskForm):
    nombre = StringField(_l("Nombre"), validators=[DataRequired(), Length(max=100)])
    email = StringField(_l("Email"), validators=[DataRequired(), Email(), Length(max=120)])
    rol = SelectField(_l("Rol"), choices=list(ROLES.items()))
    cliente_id = SelectField(_l("Empresa"), coerce=int,
                             description=_l("Solo para usuarios de clientes (rol Cliente o Cliente ChromGo)."))
    acceso_chromgo = BooleanField(_l("Acceso a Soporte ChromGo"), description=_l(
        "Solo para el rol Cliente: además de sus pedidos, puede abrir y ver tickets de ChromGo de su empresa. "
        "(Cliente ChromGo y Soporte lo tienen siempre.)"))
    activo = BooleanField(_l("Activo"), default=True)
    idioma = SelectField(_l("Idioma"), choices=[("", _l("Automático (el de su navegador)")),
                                               ("es", "Español"), ("en", "English")],
                         default="", description=_l("Idioma de la web y de los emails que recibe."))
    invitar = BooleanField(_l("Enviarle una invitación por email para que elija su contraseña"), default=True)
    password = PasswordField(
        _l("Contraseña"),
        validators=[Optional(), Length(min=10)],
        description=_l("Opcional si le envías la invitación. Al editar, déjala vacía para no cambiarla."),
    )
    submit = SubmitField(_l("Guardar"))

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self._usuario = usuario
        # Con Soporte ChromGo en pausa no se ofrecen sus roles (salvo el que ya tenga este usuario)
        self.rol.choices = list(roles_disponibles(incluir=usuario.rol if usuario is not None else None).items())
        self.soporte_activo = soporte_activo()
        self.chromgo_para_clientes = chromgo_para_clientes()     # la casilla "Acceso a Soporte ChromGo"
        self.documentos_activos = documentos_activos()
        if not self.soporte_activo:
            self.cliente_id.description = _l("Solo para usuarios de clientes (rol Cliente).")
        self.cliente_id.choices = [(0, _("— Ninguna —"))] + [
            (c.id, c.nombre) for c in db.session.scalars(
                db.select(Cliente).filter_by(activo=True).order_by(Cliente.nombre))
        ]

    def validate_cliente_id(self, campo):
        if self.rol.data in ROLES_CLIENTE and not campo.data:
            raise ValidationError(_("Un usuario cliente debe pertenecer a una empresa."))
        if self.rol.data not in ROLES_CLIENTE:
            campo.data = 0  # solo los clientes tienen empresa

    def validate_email(self, campo):  # ¡ojo! debe llamarse validate_<nombre_del_campo>
        campo.data = campo.data.strip().lower()
        existente = db.session.scalar(db.select(User).filter_by(email=campo.data))
        if existente and existente is not self._usuario:
            raise ValidationError(_("Ya existe un usuario con ese email."))

    def validate(self, extra_validators=None):
        # Usuario nuevo: o contraseña o invitación. Va aquí y no en validate_password
        # porque Optional() corta la validación del campo cuando está vacío.
        ok = super().validate(extra_validators)
        invitar = self.invitar.data if "invitar" in self._fields else False
        if self._usuario is None and not self.password.data and not invitar:
            self.password.errors = list(self.password.errors) + [_("Pon una contraseña o marca «Enviarle una invitación».")]
            ok = False
        return ok
