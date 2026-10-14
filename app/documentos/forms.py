from flask_babel import lazy_gettext as _l
from flask_wtf import FlaskForm
from flask_wtf.file import FileField
from wtforms import SelectField, StringField, SubmitField, TextAreaField
from wtforms.validators import DataRequired, Length, Optional

from app.models import CATEGORIAS_DOCUMENTO

AYUDA_ARCHIVO = _l("Hasta 40 MB. PDF, Office, imágenes, SVG/AI/EPS (logos), fuentes, ZIP…")


class DocumentoForm(FlaskForm):
    """Subir un documento nuevo (con su primera versión)."""
    categoria = SelectField(_l("Carpeta"), choices=list(CATEGORIAS_DOCUMENTO.items()))
    titulo = StringField(_l("Título"), validators=[DataRequired(), Length(max=150)],
                         description=_l("Cómo lo buscará la gente, p. ej. «Logo Yikon horizontal (color)»."))
    descripcion = TextAreaField(_l("Descripción"), validators=[Optional(), Length(max=2000)],
                                description=_l("Para qué sirve, cuándo usarlo, formato…"))
    archivo = FileField(_l("Archivo"), description=AYUDA_ARCHIVO)
    submit = SubmitField(_l("Subir documento"))


class EditarDocumentoForm(FlaskForm):
    """Cambiar título, carpeta o descripción (el archivo se cambia con "Nueva versión")."""
    categoria = SelectField(_l("Carpeta"), choices=list(CATEGORIAS_DOCUMENTO.items()))
    titulo = StringField(_l("Título"), validators=[DataRequired(), Length(max=150)])
    descripcion = TextAreaField(_l("Descripción"), validators=[Optional(), Length(max=2000)])
    submit = SubmitField(_l("Guardar"))


class VersionForm(FlaskForm):
    archivo = FileField(_l("Archivo nuevo"), description=AYUDA_ARCHIVO)
    nota = StringField(_l("Qué cambia"), validators=[Optional(), Length(max=300)],
                       description=_l("Opcional, p. ej. «Nuevo pie con la dirección de Valencia»."))
    submit = SubmitField(_l("Subir versión"))
