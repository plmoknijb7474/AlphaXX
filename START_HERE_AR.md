# AlphaX v1.5.0 — ابدأ من هنا

هذه النسخة تصحح ربط النماذج، وتتيح لك إضافة أي نموذج Google AI Studio من لوحة الأدمن مع System Prompt خاص به، وتضيف أداة تفاعلية لإدخال رابط Supabase داخل `.env` من Bash دون إظهاره على الشاشة.

## النماذج الافتراضية

| الاسم الوهمي الظاهر للمشترك | المعرّف الداخلي لدى Google AI Studio | مستويات التفكير |
|---|---|---|
| Y5Z Coder Pro | `gemma-4-26b-a4b-it` | `minimal` / `high` |
| AlphaX Pro | `gemini-3.6-flash` | `minimal` / `low` / `medium` / `high` |
| AlphaX Max | `gemma-4-31b-it` | `minimal` / `high` |

اعتمدت أن المقصود بـ AlphaX Max هو نموذج Gemma 4 31B IT، أي النموذج الآخر من عائلة Gemma 4. تستطيع تغيير المعرّف لاحقاً من صفحة Models & Prompts.

المعرّفات ومستويات التفكير متوافقة مع توثيق Google الحالي: Gemini 3.6 Flash يدعم `minimal/low/medium/high`، وGemma 4 26B و31B يدعمان `minimal/high`. راجع:
- https://ai.google.dev/gemini-api/docs/models/gemini-3.6-flash
- https://ai.google.dev/gemma/docs/core/gemma_on_gemini_api

## إضافة نموذج جديد بنفسك

من لوحة الأدمن افتح **Models & Prompts → Add a Model** ثم أدخل:

1. الاسم الوهمي الذي سيظهر للمشترك، مثل `AlphaX Research`.
2. Public Model ID الذي سيستخدمه المشترك في OpenCode، مثل `alphax-research`.
3. Google Model ID الرسمي كما يظهر في Google AI Studio/توثيق Gemini API.
4. System Prompt خاص بهذا النموذج — الحقل إلزامي ولا يمكن إنشاء نموذج دون تعليماته.
5. مستويات التفكير المدعومة وJSON الخاص بالـvariants والـdefaults، ثم قدرات الصور والأدوات والبث والوصف العام.

بعد الحفظ، افتح حساب كل مشترك وأضف له مفتاح Google AI Studio واحداً أو عدة مفاتيح لهذا النموذج، ثم امنحه صلاحية النموذج. لن يظهر للمشترك اسم Google أو المعرّف الداخلي أو المفتاح أو System Prompt؛ سيظهر الاسم الوهمي فقط. جميع النماذج الجديدة تستخدم Google AI Studio حصراً.

## مفاتيح API والتوجيه

- يمكنك إضافة عدة مفاتيح Google لكل مستخدم ولكل نموذج.
- التبديل التلقائي يكون بين مفاتيح ذلك المستخدم والنموذج فقط.
- لا يوجد Pool مشترك أو استعارة مفتاح من مستخدم آخر.
- لكل نموذج System Prompt منفصل يحقنه الخادم في كل طلب.
- يستطيع المشترك إنشاء عدة مفاتيح AlphaX API مستقلة، وإلغاء كل مفتاح منفرداً.
- OpenCode يستخدم مفتاح AlphaX وعنوان الخدمة وPublic Model IDs فقط.

## ترقية الإصدار

- الإصدار: `1.5.0`
- المشروع: `/home/AlphaX/alpha_deploy/AlphaAPI`
- البيئة: `/home/AlphaX/.virtualenvs/alphax-venv`
- الموقع: `AlphaX.pythonanywhere.com`

الترحيل V8 يصحح ربط النماذج الافتراضية إلى:
- Y5Z Coder Pro → Gemma 4 26B A4B IT.
- AlphaX Pro → Gemini 3.6 Flash.
- AlphaX Max → Gemma 4 31B IT.

يحافظ الترحيل على System Prompts ومفاتيح Google الحالية والمنح والاشتراكات وأوامر الدفع ومفاتيح AlphaX. لا يغير أسماء النماذج العامة.

## ربط Supabase من Bash دون تحرير `.env` يدوياً

بعد نجاح تشغيل الإصدار على SQLite، وقبل تغيير أي إعداد، أنشئ نسخة نهائية للقاعدة وملف `.env`:

```bash
cd /home/AlphaX/alpha_deploy/AlphaAPI
source /home/AlphaX/.virtualenvs/alphax-venv/bin/activate
python scripts/backup_sqlite_before_supabase.py
```

بعدها شغّل أداة إدخال الرابط:

```bash
python scripts/configure_supabase.py
```

ستطلب منك لصق PostgreSQL connection string في إدخال مخفي. انسخه من Supabase → Connect، ويفضل **Session Pooler / port 5432**. الأداة:

- تتحقق من صيغة رابط Supabase وتفرض SSL.
- تختبر الاتصال فعلياً.
- تتأكد أن public schema فارغ قبل النقل.
- تنشئ نسخة احتياطية من `.env` وتحدّث `DATABASE_URL` فقط بعد نجاح الفحص.
- لا تطبع كلمة المرور ولا تعدّل `.env` إذا فشل الاتصال.

**تنبيه استضافة:** الوصول إلى PostgreSQL خارجي من PythonAnywhere يتطلب حساباً مدفوعاً. الحساب المجاني يقيّد اتصالات الإنترنت الخارجة، لذلك قد يفشل اختبار الاتصال حتى لو كان رابط Supabase صحيحاً. راجع https://help.pythonanywhere.com/pages/Postgres/ و https://help.pythonanywhere.com/pages/403ForbiddenError/ .

بعد نجاح الأداة شغّل معاينة النقل أولاً:

```bash
python scripts/migrate_sqlite_to_supabase.py --source /home/AlphaX/alpha_deploy/AlphaAPI/alpha.db
```

راجع أعداد الصفوف، ثم نفّذ النقل صراحةً:

```bash
python scripts/migrate_sqlite_to_supabase.py --source /home/AlphaX/alpha_deploy/AlphaAPI/alpha.db --apply
```

لا تستخدم `--apply` إلا بعد التأكد أن قاعدة Supabase الجديدة هي القاعدة المقصودة وفارغة. الأداة ترفض أي public schema غير فارغ. لا تحذف SQLite بعد النقل.

## الحفاظ على الأسرار

- لا تغيّر `SECRET_KEY` الحالي.
- لا تغيّر `FERNET_KEY` الحالي، فهو ضروري لفك مفاتيح Google المشفرة.
- لا تضع مفاتيح Google في `.env`؛ تظل مرتبطة بكل مستخدم/نموذج ومشفرة في قاعدة البيانات.
- لا تضع رابط Supabase أو كلمة المرور في Git أو في المحادثة.
- المفتاح الذي ظهر سابقاً في المحادثة يجب إلغاؤه وعدم إعادة استخدامه.

## الفحوص

شغّل:

```bash
python -m compileall -q app tests scripts
pytest -q
curl -sS -i https://AlphaX.pythonanywhere.com/health/ready
```

الاختبارات المحلية تستخدم استجابات مزود وهمية؛ نجاحها لا يثبت صلاحية مفتاح Google الفعلي. نفّذ طلباً حقيقياً صغيراً على حساب تجريبي قبل تفعيل الخدمة للعملاء.
