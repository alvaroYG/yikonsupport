from flask_wtf import FlaskForm
from flask_babel import lazy_gettext as _l
from wtforms import BooleanField, PasswordField, StringField, SubmitField
from wtforms.validators import DataRequired, Email, EqualTo, Length


class LoginForm(FlaskForm):
    email = StringField(_l("Email"), validators=[DataRequired(), Email()])
    password = PasswordField(_l("Contraseña"), validators=[DataRequired()])
    recordar = BooleanField(_l("Recordarme"))
    submit = SubmitField(_l("Entrar"))


class CambiarPasswordForm(FlaskForm):
    actual = PasswordField(_l("Contraseña actual"), validators=[DataRequired()])
    nueva = PasswordField(_l("Nueva contraseña"), validators=[DataRequired(), Length(min=10)])
    confirmar = PasswordField(
        _l("Repite la nueva contraseña"),
        validators=[DataRequired(), EqualTo("nueva", message=_l("No coinciden."))],
    )
    submit = SubmitField(_l("Cambiar contraseña"))


class OlvideForm(FlaskForm):
    email = StringField(_l("Tu email"), validators=[DataRequired(), Email()])
    submit = SubmitField(_l("Enviarme un enlace"))


class RestablecerForm(FlaskForm):
    nueva = PasswordField(_l("Nueva contraseña"), validators=[DataRequired(), Length(min=10)])
    confirmar = PasswordField(_l("Repite la nueva contraseña"),
                              validators=[DataRequired(), EqualTo("nueva", message=_l("No coinciden."))])
    submit = SubmitField(_l("Guardar contraseña"))
