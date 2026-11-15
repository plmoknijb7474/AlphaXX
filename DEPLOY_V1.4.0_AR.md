# نشر AlphaX v1.4.0 على PythonAnywhere

> هذه ترقية فوق المشروع الموجود. لا تنشئ موقعاً جديداً. الأوامر تحفظ `.env` وقاعدة SQLite والملفات المرفوعة.

## 1) ارفع ملف ZIP

ارفع `AlphaX-AlphaAPI-v1.4.0-GoogleAIStudio.zip` إلى `/home/AlphaX/` من تبويب Files.

## 2) نفّذ كتلة التحديث

```bash
set -e
ZIP=/home/AlphaX/AlphaX-AlphaAPI-v1.4.0-GoogleAIStudio.zip
PROJECT=/home/AlphaX/alpha_deploy/AlphaAPI
VENV=/home/AlphaX/.virtualenvs/alphax-venv
STAMP=$(date +%Y%m%d-%H%M%S)
STAGE=/home/AlphaX/alpha_deploy/staging-v140-$STAMP
mkdir -p /home/AlphaX/backups "$STAGE"
test -f "$ZIP"
test -f "$PROJECT/.env"
tar -czf "/home/AlphaX/backups/AlphaAPI-before-v1.4.0-$STAMP.tar.gz" -C /home/AlphaX/alpha_deploy AlphaAPI
unzip -t "$ZIP"
unzip -q "$ZIP" -d "$STAGE"
test -f "$STAGE/app/main.py"
test -f "$STAGE/requirements.txt"
python - "$STAGE" "$PROJECT" <<'PY'
import re, sys, shutil
from pathlib import Path
src, dst = map(Path, sys.argv[1:3])
protected_roots = {"uploads", "storage", "media", "receipts", "instance", "logs"}
db_pattern = re.compile(r"\.(?:db|sqlite|sqlite3)(?:-(?:wal|shm|journal))?$", re.I)
def protected(rel):
    return rel.name == ".env" or bool(db_pattern.search(rel.name)) or any(part in protected_roots for part in rel.parts)
# Update files from the release but preserve secrets, databases and user-uploaded files.
for item in src.rglob("*"):
    rel = item.relative_to(src)
    if protected(rel):
        continue
    target = dst / rel
    if item.is_dir():
        target.mkdir(parents=True, exist_ok=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
print("V1.4.0 files copied; .env, SQLite databases and user uploads were preserved.")
PY
source "$VENV/bin/activate"
cd "$PROJECT"
python -m pip install -r requirements.txt
python -m compileall -q app tests scripts
pytest -q
python -c "from app.main import app; print(app.title, app.version)"
pa website reload --domain AlphaX.pythonanywhere.com
```

المفروض تنتهي الاختبارات بـ `48 passed` ويظهر `AlphaX 1.4.0`.

## 3) فحص الموقع

```bash
curl -sS https://AlphaX.pythonanywhere.com/health
curl -sS -i https://AlphaX.pythonanywhere.com/health/ready
tail -n 60 /var/log/alphax.pythonanywhere.com.error.log
```

يجب أن تكون `/health/ready` برمز `200` وبحالة `ready`. رمز `303` من الصفحة الرئيسية قد يكون مجرد تحويل لتسجيل الدخول.

## 4) أعمال مطلوبة بعد الترقية

1. افتح `/admin/providers`؛ يجب أن يظهر Google AI Studio فقط.
2. افتح `/admin/models` وتأكد من معرفات النماذج الثلاثة ومن وجود System Prompt غير فارغ لكل نموذج.
3. مفاتيح المزودين الخارجيين القديمة المرتبطة بـ Y5Z Coder Pro وAlphaX Pro ستُعطّل في الترحيل، ولن تُرسل إلى Google. أضف مفاتيح Google AI Studio الجديدة من حساب كل مشترك ولكل نموذج.
4. مفاتيح AlphaX Max القديمة التي كانت Google تبقى فعالة.
5. نزّل إعداد OpenCode من حساب مشترك تجريبي وتأكد من ظهور الأسماء الوهمية فقط وخيارات التفكير الصحيحة.

لا تغيّر `DATABASE_URL` أو `SECRET_KEY` أو `FERNET_KEY`. لا تنفذ ترحيل Supabase ضمن هذه الخطوة.

## التراجع

إذا تعطل الموقع، لا تحذف النسخة الجديدة أو قاعدة البيانات. استعد أرشيف النسخة الاحتياطية الذي ظهر في `/home/AlphaX/backups/AlphaAPI-before-v1.4.0-<timestamp>.tar.gz` وفق خطوات التراجع في دليل PythonAnywhere أو اطلب المساعدة قبل الكتابة فوق مجلد الموقع.
