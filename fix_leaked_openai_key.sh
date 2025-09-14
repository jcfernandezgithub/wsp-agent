#!/usr/bin/env bash
set -euo pipefail

BRANCH_DEFAULT="master"
REMOTE_DEFAULT="origin"

echo "==> Verificando que estás dentro de un repo git..."
git rev-parse --is-inside-work-tree >/dev/null

CURRENT_BRANCH="$(git rev-parse --abbrev-ref HEAD)"
REMOTE="${REMOTE_DEFAULT}"
BRANCH="${BRANCH_DEFAULT}"

echo "==> Branch actual: ${CURRENT_BRANCH}"
echo "==> Usando remoto: ${REMOTE}"
echo "==> Target branch a pushear: ${BRANCH}"

# 1) .gitignore + sacar .env del índice si estuviera
echo "==> Asegurando que .env esté ignorado y fuera del índice..."
touch .gitignore
if ! grep -qE '(^|/)\.env(\.|$|/)?' .gitignore; then
  {
    echo ".env"
    echo ".env.*"
  } >> .gitignore
fi

# quitar .env del índice si está trackeado
git rm --cached .env 2>/dev/null || true

# commitear cambios si los hay
if ! git diff --cached --quiet; then
  git add .gitignore
  git commit -m "chore: ignore .env and remove from index"
else
  echo "==> No hay cambios que commitear en esta etapa."
fi

# 2) Reescribir historia para borrar .env de TODOS los commits
echo "==> Reescribiendo historia para eliminar .env de todos los commits (git filter-branch)..."
# Nota: filter-branch es parte de git (aunque esté deprecated). No usa tools externas.
git filter-branch --force --index-filter \
  'git rm --cached --ignore-unmatch .env' \
  --prune-empty --tag-name-filter cat -- --all

# 3) Limpiar refs y hacer GC agresivo
echo "==> Limpiando refs originales y ejecutando GC..."
rm -rf .git/refs/original/
git for-each-ref --format="delete %(refname)" refs/original | git update-ref --stdin || true
git reflog expire --expire=now --all
git gc --prune=now --aggressive

# 4) Verificación: buscar posibles restos de "sk-" en la historia
echo "==> Verificando que no queden posibles claves (patrón 'sk-') en el historial..."
set +e
LEAKS="$(git rev-list --all | xargs -I{} git grep -n "sk-" {} 2>/dev/null)"
set -e
if [ -n "$LEAKS" ]; then
  echo "!! Atención: Se encontraron coincidencias de 'sk-' en la historia:"
  echo "$LEAKS"
  echo "Revisá los paths/commits listados y repetí el proceso ajustando el filtro si hace falta."
  echo "Saliendo sin pushear por seguridad."
  exit 2
else
  echo "==> OK: no se encontraron coincidencias de 'sk-' en la historia."
fi

# 5) Push forzado (historia reescrita)
echo "==> Haciendo push --force de todos los branches y tags..."
git push --force ${REMOTE} --all || {
  echo "!! El push forzado de branches falló (¿branch protegido en remoto?)."
  echo "   Desprotegé temporalmente ${BRANCH} en GitHub y reintentá:"
  echo "   git push --force ${REMOTE} --all"
  exit 3
}
git push --force ${REMOTE} --tags || {
  echo "!! El push forzado de tags falló."
  echo "   Reintentá: git push --force ${REMOTE} --tags"
  exit 4
}

echo "==> Listo. Historia limpia y push forzado realizado."
echo "   Recordá avisar a colaboradores que hagan:"
echo "     git fetch origin"
echo "     git reset --hard origin/${BRANCH}"
