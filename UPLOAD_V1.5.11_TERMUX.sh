#!/data/data/com.termux/files/usr/bin/bash
set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$HOME/AlphaXX-v1.5.11"

fail() {
  echo
  echo "توقفت العملية: $*" >&2
  echo "لم يتم تنفيذ push بعد نقطة الفشل." >&2
  exit 1
}
trap 'fail "خطأ عند السطر $LINENO"' ERR

command -v python >/dev/null 2>&1 || fail "Python غير مثبت. نفّذ pkg install python -y"
command -v git >/dev/null 2>&1 || fail "Git غير مثبت. نفّذ pkg install git -y"
command -v gh >/dev/null 2>&1 || fail "GitHub CLI غير مثبت. نفّذ pkg install gh -y"
[ -f "$SCRIPT_DIR/requirements.txt" ] || fail "شغّل هذا السكربت من مجلد نسخة الإصدار المفكوكة."
[ -f "$SCRIPT_DIR/VERSION" ] || fail "ملف VERSION غير موجود."
[ "$(tr -d '\r\n' < "$SCRIPT_DIR/VERSION")" = "1.5.11" ] || fail "هذه الحزمة ليست v1.5.11."

[ -d "$REPO_DIR/.git" ] || fail "لم أجد نسخة Git المحلية في $REPO_DIR. احتفظ بنسخة المستودع التي أنشأناها سابقاً."
cd "$REPO_DIR"
[ "$(git branch --show-current)" = "main" ] || fail "المستودع المحلي ليس على main؛ لن أبدّل الفرع تلقائياً."
case "$(git remote get-url origin)" in
  *plmoknijb7474/AlphaXX*) ;;
  *) fail "origin لا يشير إلى plmoknijb7474/AlphaXX." ;;
esac

echo "1/7 - تثبيت الحزم التي ظهرت ناقصة في Termux"
python -m pip install --disable-pip-version-check --no-cache-dir --retries 2 --timeout 30 \
  'pydantic-settings>=2.4,<3.0' 'python-multipart>=0.0.9'

python - <<'PY'
import pydantic_settings, multipart, pytest
print('pydantic-settings: OK')
print('python-multipart: OK')
print('pytest: OK')
PY

echo "2/7 - فحص صياغة ملفات Python"
cd "$SCRIPT_DIR"
python -m compileall -q app tests scripts

echo "3/7 - تشغيل الاختبارات الثمانين كاملة"
python -m pytest -q
find "$SCRIPT_DIR" -type d \( -name __pycache__ -o -name .pytest_cache \) -prune -exec rm -rf {} +

echo "4/7 - التحقق من نسخة GitHub قبل نسخ الملفات"
cd "$REPO_DIR"
git fetch origin main
if ! git merge-base --is-ancestor origin/main HEAD; then
  fail "GitHub main أحدث من النسخة المحلية. لم أستخدم reset أو force push."
fi

echo "5/7 - تحديث ملفات المستودع المحلي من الحزمة الكاملة"
shopt -s dotglob nullglob
for item in "$SCRIPT_DIR"/*; do
  name="${item##*/}"
  case "$name" in
    UPLOAD_V1.5.11_TERMUX.sh|.git|.pytest_cache|__pycache__) continue ;;
  esac
  cp -a "$item" "$REPO_DIR/"
done
rm -f "$REPO_DIR/apply_alphax_patch.py"
git diff --check

# Stage only release files; never stage .env, local databases, or other user files.
git add \
  app/main.py \
  app/services/provider_client.py \
  app/templates/models.html \
  app/templates/account.html \
  app/templates/customer_auth.html \
  app/templates/key_reveal.html \
  app/templates/layout.html \
  tests/test_apinex_regolo_migration.py \
  tests/test_ui_release.py \
  tests/test_health_readiness.py \
  VERSION \
  PATCH_NOTES_V1.5.11_AR.md \
  UPGRADE_NOTES_V1.5.11.md \
  RELEASE_TESTS_V1.5.11_AR.md

git diff --cached --check

echo "6/7 - التحقق من GitHub وإنشاء Commit"
if ! gh auth status --hostname github.com >/dev/null 2>&1; then
  gh auth login --hostname github.com --git-protocol https --web --scopes repo
fi
gh auth setup-git
GH_LOGIN="$(gh api user --jq .login)"
GH_ID="$(gh api user --jq .id)"
if ! git diff --cached --quiet; then
  git -c user.name="$GH_LOGIN" \
      -c user.email="${GH_ID}+${GH_LOGIN}@users.noreply.github.com" \
      commit -m "AlphaXX v1.5.11 - reasoning toggle fixes"
else
  echo "لا توجد تغييرات جديدة لإنشاء Commit."
fi

echo "7/7 - Push والتحقق النهائي"
git push -u origin main
LOCAL_SHA="$(git rev-parse HEAD)"
REMOTE_SHA="$(git ls-remote origin refs/heads/main | awk '{print $1}')"
[ -n "$REMOTE_SHA" ] || fail "تعذر قراءة آخر Commit من GitHub."
[ "$LOCAL_SHA" = "$REMOTE_SHA" ] || fail "Commit المحلي لا يطابق GitHub بعد الرفع."

echo
echo "=============================================="
echo "نجح الاختبار والرفع والتحقق"
echo "Version: 1.5.11"
echo "Branch: main"
echo "Commit: $LOCAL_SHA"
echo "Repository: https://github.com/plmoknijb7474/AlphaXX"
echo "=============================================="
echo "ملاحظة: يلزم اختبار حي مع Regolo للتأكد من تنفيذ OFF على gemma4-31b."
