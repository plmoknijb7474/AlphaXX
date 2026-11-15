# ربط AlphaX مع Supabase ونقل SQLite بأمان

## متطلبات مهمة

- مشروع Supabase جديد أو public schema فارغ تماماً.
- PythonAnywhere بحساب مدفوع للاتصال الخارجي بـ PostgreSQL؛ الحسابات المجانية تقيّد الاتصالات الخارجة ولا تدعم الاتصال الخارجي بـ PostgreSQL مباشرة.
- ملف `.env` الحالي وقاعدة SQLite والـ `SECRET_KEY` والـ `FERNET_KEY` محفوظة.

مراجع PythonAnywhere الرسمية:
- https://help.pythonanywhere.com/pages/Postgres/
- https://help.pythonanywhere.com/pages/403ForbiddenError/

## 1. أنشئ مشروع Supabase

1. افتح https://supabase.com/dashboard وأنشئ مشروعاً باسم AlphaX.
2. احفظ كلمة مرور قاعدة البيانات.
3. افتح **Connect** ثم اختر **Session Pooler** (موصى به لـPythonAnywhere عند توفر اتصال TCP الخارجي) وانسخ PostgreSQL URI، عادةً على المنفذ `5432`.
4. لا تنسخ رابط HTTPS الخاص بـSupabase ولا anon/service_role key؛ المطلوب PostgreSQL connection string.

## 2. خذ نسخة نهائية من SQLite وملف `.env` أولاً

**هذه الخطوة تسبق إدخال رابط Supabase.** شغّلها بينما `DATABASE_URL` ما زال يشير إلى SQLite:

```bash
cd /home/AlphaX/alpha_deploy/AlphaAPI
source /home/AlphaX/.virtualenvs/alphax-venv/bin/activate
python scripts/backup_sqlite_before_supabase.py
```

سيطبع الأمر مسارين `SQLITE_BACKUP=...` و`ENV_BACKUP=...`. احتفظ بهما، وانسخ مسار `SQLITE_BACKUP` لاستخدامه في أوامر المعاينة والترحيل لاحقاً. الأداة تتحقق من سلامة SQLite، تنسخ القاعدة باستخدام SQLite backup API، وتحفظ `.env` بصلاحيات 600.

## 3. أدخل رابط Supabase من Bash — دون تحرير `.env` يدوياً

بعد نجاح النسخة الاحتياطية، نفّذ:

```bash
cd /home/AlphaX/alpha_deploy/AlphaAPI
source /home/AlphaX/.virtualenvs/alphax-venv/bin/activate
python scripts/configure_supabase.py
```

سيطلب منك لصق الرابط داخل Bash بإدخال مخفي:

```text
Paste the Supabase PostgreSQL URI (input hidden):
```

الصق PostgreSQL connection string الذي نسخته من Supabase → Connect، ثم اضغط Enter. الأداة:

- تتحقق من أن المضيف تابع لـSupabase وأن بيانات URI مكتملة.
- تضيف `sslmode=require` وتختار برنامج تشغيل psycopg 3.
- تختبر الاتصال فعلياً باستخدام `SELECT 1`.
- ترفض قاعدة `public` غير الفارغة.
- تنشئ نسخة احتياطية إضافية من `.env` بصلاحيات 600.
- تستبدل `DATABASE_URL` فقط بعد نجاح الاتصال، وتبقي `SECRET_KEY` و`FERNET_KEY` وبقية الإعدادات دون تغيير.
- لا تطبع كلمة المرور، ولا تعدّل `.env` إذا فشل الاتصال.

**لا تلصق الرابط في المحادثة.** ألصقه فقط عند مطالبة Bash به. استخدم Session Pooler على المنفذ 5432 إن كان متاحاً. الأداة تدعم كذلك Transaction Pooler على المنفذ 6543، لكن Session Pooler هو الاختيار المفضل لخادم PythonAnywhere طويل العمر.

لا تشغّلها على PythonAnywhere Free وتتوقع أن تعمل: الاتصال الخارجي بـPostgreSQL يتطلب خطة مدفوعة.

## 4. معاينة الترحيل — للقراءة فقط

```bash
cd /home/AlphaX/alpha_deploy/AlphaAPI
source /home/AlphaX/.virtualenvs/alphax-venv/bin/activate
python scripts/migrate_sqlite_to_supabase.py
```

إذا لم تمرر `--source`، تختار الأداة أحدث نسخة احتياطية أنشأتها الخطوة 2 تلقائياً، وتطبع مسار المصدر المختار. تأكد من أعداد المستخدمين والاشتراكات والمفاتيح والمدفوعات. الهدف يجب أن يكون public schema فارغاً. لا تكمل إذا كانت الأرقام غير منطقية.

## 5. تنفيذ الترحيل

```bash
python scripts/migrate_sqlite_to_supabase.py --source "/home/AlphaX/backups/PASTE-THE-EXACT-SQLITE_BACKUP-PATH-HERE.db" --apply
```

لا تضغط Enter على `--apply` إلا بعد مراجعة المعاينة. الأداة تنشئ المخطط وتنسخ الصفوف وتحافظ على المعرفات وتعيد ضبط PostgreSQL sequences. المصدر SQLite لا يتغير.

## 6. تشغيل التطبيق على Supabase

```bash
pa website reload --domain AlphaX.pythonanywhere.com
curl -sS -i https://AlphaX.pythonanywhere.com/health/ready
```

ثم سجّل دخول الأدمن وتحقق من المستخدمين والاشتراكات والمدفوعات ومفاتيح المزود والنماذج. اختبر `GET /v1/models` وطلب `POST /v1/chat/completions` عبر OpenCode بحساب تجريبي.

## 7. التراجع

ملف `.env` القديم موجود في `/home/AlphaX/backups/AlphaX-env-before-Supabase-*`. لعرض النسخ:

```bash
ls -lt /home/AlphaX/backups/AlphaX-env-before-Supabase-*
```

لا تنفذ `cp` عشوائياً إذا كان لديك أكثر من نسخة؛ اختر النسخة التي سبقت تغيير DATABASE_URL. ثم:

```bash
cp /home/AlphaX/backups/EXACT-ENV-BACKUP-FILENAME /home/AlphaX/alpha_deploy/AlphaAPI/.env
chmod 600 /home/AlphaX/alpha_deploy/AlphaAPI/.env
pa website reload --domain AlphaX.pythonanywhere.com
```

احتفظ بقاعدة SQLite ولا تحذفها حتى تجتاز اختبارات الإنتاج. لا تغيّر `SECRET_KEY` أو `FERNET_KEY`.
