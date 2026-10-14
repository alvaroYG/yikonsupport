# Git para la plataforma, paso a paso

Git guarda el **historial** del proyecto: cada vez que haces un cambio que funciona,
le haces una "foto" (un *commit*). Puedes volver a cualquier foto anterior, ver qué
cambió y cuándo, y probar cosas sin miedo a romper lo que ya va.

Con Git se acaban los problemas que hemos tenido con los zips:

- **Una sola carpeta**, siempre la misma. Nada de `plataforma/plataforma`.
- **Tu `.env`, `dev.db` e `instance/` no se tocan nunca.** Git los ignora gracias al
  archivo `.gitignore`, así que no viajan con el código ni se pueden perder al
  actualizar.
- Cuando yo te pase cambios, verás **exactamente qué líneas cambian** antes de aceptarlos.
- IT lo va a necesitar para el despliegue: el servidor descargará el código con Git.

---

## 1. Instalar Git (una vez)

1. Descarga **Git for Windows**: https://git-scm.com/download/win e instálalo con las
   opciones por defecto.
2. Abre una terminal nueva (PowerShell o la de VS Code) y comprueba:
   ```
   git --version
   ```
3. Dile a Git quién eres (sale en cada commit):
   ```
   git config --global user.name "Álvaro Ballesteros"
   git config --global user.email "tu.email@yikon…"
   git config --global init.defaultBranch main
   ```

> Si App Control de Windows bloquea Git, es un caso para IT: es una herramienta
> estándar y la van a necesitar igualmente para desplegar.

## 2. Convertir tu carpeta en un repositorio (una vez)

Desde la carpeta del proyecto, la que tiene `run.py`:

```
git init
git status
```

`git status` te enseña qué archivos va a guardar Git. **Comprueba que NO aparecen**
`.env`, `dev.db`, `instance/` ni `.venv/`. Si aparece alguno, dímelo antes de seguir:
el `.gitignore` ya los excluye, pero conviene mirarlo.

Primera foto:

```
git add .
git commit -m "Versión inicial de la plataforma"
```

## 3. El día a día

| Quiero… | Comando |
|---|---|
| Ver qué he cambiado | `git status` y `git diff` |
| Guardar una foto de lo que funciona | `git add .` y luego `git commit -m "Qué he hecho"` |
| Ver el historial | `git log --oneline` |
| Deshacer cambios de un archivo que aún no he guardado | `git restore ruta/archivo` |
| Ver cómo estaba un archivo en una foto anterior | `git show <código>:ruta/archivo` |

**Consejo:** haz commits pequeños y a menudo, con mensajes que digan *qué* y *por qué*:
`"Botón Hacer un pedido unificado en la lista"` es mucho mejor que `"cambios"`.

## 4. Probar algo sin miedo: ramas

Una **rama** es una copia paralela del proyecto para probar algo. Si sale bien, la
unes a la principal; si no, la tiras y no ha pasado nada.

```
git switch -c prueba-colores       # crea la rama y te cambia a ella
# … cambias cosas, haces commits …
git switch main                    # vuelves a la versión buena
git merge prueba-colores           # si te gusta: lo traes a main
git branch -d prueba-colores       # y borras la rama
```

## 5. Recibir mis cambios

Cuando te pase una versión nueva, te daré un archivo **`.patch`** en lugar del zip entero:

```
git status                         # primero, que no tengas cambios a medias
git apply --check cambios.patch    # comprueba que encaja, sin tocar nada
git apply cambios.patch            # lo aplica
git diff                           # revisa qué ha cambiado
pip install -r requirements.txt    # por si hay librerías nuevas
flask db upgrade                   # por si hay cambios en la base de datos
python -m pytest -q                # que todo siga pasando
git add . && git commit -m "Lotes y caducidad, envíos, Excel…"
```

Si algo no te convence: `git restore .` lo deja todo como estaba antes de aplicarlo.

## 6. Copia en la nube (cuando lo decidáis con IT)

Lo normal es un repositorio **privado** en GitHub, GitLab o Azure DevOps (lo que use
Yikon). IT os dará la dirección y luego es:

```
git remote add origin <dirección-que-os-den>
git push -u origin main
```

A partir de ahí, `git push` sube tus commits. Sirve como copia de seguridad del
código, y el servidor de producción descargará el código desde ahí.

⚠️ El `.env` **nunca** se sube, ni siquiera a un repositorio privado: las claves van
aparte (el servidor tendrá su propio `.env`).
