# نشر AlphaX v1.5.0 على PythonAnywhere

ترقية فوق الموقع الحالي، ولا تنشئ موقعاً جديداً. المسارات المعتمدة:

- المشروع: `/home/AlphaX/alpha_deploy/AlphaAPI`
- البيئة: `/home/AlphaX/.virtualenvs/alphax-venv`
- الدومين: `AlphaX.pythonanywhere.com`

## 1. ارفع ZIP

ارفع `AlphaX-AlphaAPI-v1.5.0-GoogleAIStudio.zip` إلى `/home/AlphaX/`.

## 2. النسخ الاحتياطي واستخراج الإصدار

```bash
set -e
ZIP=/home/AlphaX/AlphaX-AlphaAPI-v1.5.0-GoogleAIStudio.zip
PROJECT=/home/AlphaX/alpha_deploy/AlphaAPI
VENV=/home/AlphaX/.virtualenvs/alphax-venv
STAMP=$(date +%Y%m%d-%H%M%S)
STAGE=/home/AlphaX/alpha_deploy/staging-v150-$STAMP
mkdir -p /home/AlphaX/backups "$STAGE"
test -f "$ZIP" && test -f "$PROJECT/.env"
tar -czf "/home/AlphaX/backups/AlphaAPI-before-v1.5.0-$STAMP.tar.gz" -C /home/AlphaX/alpha_deploy AlphaAPI
unzip -t "$ZIP"
unzip -q "$ZIP" -d "$STAGE"
test -f "$STAGE/app/main.py" && test -f "$STAGE/requirements.txt"
python - "$STAGE" "$PROJECT" <<'PY'
import re, sys, shutil
from pathlib import Path
src, dst = map(Path, sys.argv[1:3])
protected_roots = {"uploads", "storage", "media", "receipts", "instance", "logs"}
db_pattern = re.compile(r"\.(?:db|sqlite|sqlite3)(?:-(?:wal|shm|journal))?$", re.I)
def protected(rel):
    return rel.name == ".env" or bool(db_pattern.search(rel.name)) or any(part in protected_roots for part in rel.parts)
for item in src.rglob("*"):
    rel = item.relative_to(src)
    if protected(rel): continue
    target = dst / rel
    if item.is_dir(): target.mkdir(parents=True, exist_ok=True)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(item, target)
print("v1.5.0 code copied; .env, databases and user uploads preserved")
PY
source "$VENV/bin/activate"
cd "$PROJECT"
python -m pip install -r requirements.txt
python -m compileall -q app tests scripts
pytest -q
python -c "from app.main import app; print(app.title, app.version)"
pa website reload --domain AlphaX.pythonanywhere.com
```

المطلوب `53 passed` و`AlphaX 1.5.0`. بعد ذلك افحص:

```bash
curl -sS -i https://AlphaX.pythonanywhere.com/health/ready
tail -n 60 /var/log/alphax.pythonanywhere.com.error.log
```

## 3. خريطة النماذج

- Y5Z Coder Pro → `gemma-4-26b-a4b-it`
- AlphaX Pro → `gemini-3.6-flash`
- AlphaX Max → `gemma-4-31b-it`

يطبّق V8 مرة واحدة عند بدء التشغيل إذا لم يكن marker موجوداً. لا يحذف System Prompts أو Google keys أو الاشتراكات أو المنح.

## 4. إضافة نموذج جديد

افتح `/admin/models`، وأكمل Add a Model. يجب أن يكون له public alias وGoogle model ID صحيح وSystem Prompt خاص. ثم أضف مفاتيح Google لهذا النموذج في حساب كل مشترك وامنحه الصلاحية. لا يضاف النموذج إلى قائمة المستخدم إلا بعد ضبط System Prompt والمفتاح والمنحة.

## 5. إعداد Supabase

بعد نجاح نسخة SQLite على v1.5.0، راجع `SUPABASE_SETUP_AR.md`. أولاً خذ نسخة نهائية من SQLite و`.env` ثم أدخل الرابط:

```bash
cd /home/AlphaX/alpha_deploy/AlphaAPI
source /home/AlphaX/.virtualenvs/alphax-venv/bin/activate
python scripts/backup_sqlite_before_supabase.py
python scripts/configure_supabase.py
```

أداة `configure_supabase.py` تطلب منك لصق الرابط في Bash بإدخال مخفي ثم تختبره وتكتبه إلى `.env` تلقائياً. بعدها نفّذ `python scripts/migrate_sqlite_to_supabase.py` للمعاينة ثم `python scripts/migrate_sqlite_to_supabase.py --apply` للنقل بعد مراجعة مسار المصدر وأعداد الصفوف. PythonAnywhere يتطلب حساباً مدفوعاً للاتصال بقاعدة PostgreSQL خارجية.

## تراجع آمن

احتفظ بالأرشيف `/home/AlphaX/backups/AlphaAPI-before-v1.5.0-<timestamp>.tar.gz`، وبنسخة SQLite و`.env`. لا تنشئ `SECRET_KEY` أو `FERNET_KEY` جديدين. لا تنفذ أي حذف يدوياً عند فشل الترقية.
