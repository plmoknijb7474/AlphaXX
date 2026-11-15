# نشر AlphaX v1.5.4 على Render

هذه الحزمة معدّة لخدمة Render Web Service باستخدام Docker وFastAPI/Uvicorn.

## قبل النشر

- استخدم PostgreSQL خارجياً مثل Supabase. لا تستخدم SQLite على Render Free لأن نظام الملفات للخدمة مؤقت وقد تفقد قاعدة البيانات عند إعادة النشر أو إعادة التشغيل.
- لا ترفع ملف `.env` أو أي قاعدة بيانات أو مفاتيح API إلى GitHub.
- الخطة المجانية قد توقف الخدمة عند الخمول، لذلك قد يتأخر أول طلب حتى تستيقظ الخدمة. ليست مناسبة كضمان تشغيل تجاري مستمر.

## النشر من GitHub

1. فك ضغط الحزمة وارفع محتويات المجلد إلى مستودع GitHub جديد أو فرع مستقل. يجب أن تكون ملفات `Dockerfile` و`render.yaml` في جذر المستودع بجانب `requirements.txt` ومجلد `app`.
2. افتح Render ثم New + → Blueprint، واختر المستودع والفرع.
3. سيقرأ Render ملف `render.yaml` وينشئ خدمة `alphax-api` بخطة Free ومنطقة Frankfurt.
4. في Environment للخدمة، أدخل:
   - `DATABASE_URL`: رابط PostgreSQL من Supabase (يفضّل Session Pooler مع `sslmode=require`).
   - `SECRET_KEY`: قيمة عشوائية طويلة وفريدة.
   - `FERNET_KEY`: مفتاح Fernet صالح، أنشئه محلياً بالأمر أدناه.
   - `ADMIN_PASSWORD`: كلمة مرور قوية لا تقل عن 14 محرفاً.
   - `PUBLIC_BASE_URL`: رابط Render الكامل مثل `https://alphax-api.onrender.com` بعد معرفة اسم الخدمة.
5. احفظ المتغيرات وانتظر اكتمال Build وDeploy. افحص `/health/ready` ويجب أن يعيد `status: ready`.
6. افتح `/login` وسجّل الدخول باسم `admin` وكلمة المرور التي وضعتها في `ADMIN_PASSWORD`.

## توليد FERNET_KEY محلياً

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

لا تغيّر `FERNET_KEY` بعد حفظ مفاتيح مزودي Google المشفرة في قاعدة البيانات؛ تغييرها يجعل الأسرار القديمة غير قابلة لفك التشفير.

## ملاحظات قاعدة البيانات

- الإصدار 1.5.4 يضيف الأعمدة الناقصة إلى الجداول الموجودة بشكل إضافي عند بدء التشغيل. لا يحذف صفوف المستخدمين أو الاشتراكات. راقب Render Logs بعد النشر وتأكد من اكتمال بدء التشغيل.

- إذا كانت قاعدة Supabase تحتوي جداول AlphaX بالفعل، استخدمها فقط إذا كانت قاعدة المشروع المقصودة وبنفس إصدار المخطط. لا تشغّل نقل SQLite إلى قاعدة غير فارغة.
- عند أول تشغيل على قاعدة فارغة، ينشئ التطبيق الجداول والحساب الإداري والخطط الافتراضية تلقائياً.
- إذا كنت تنقل بيانات موقع PythonAnywhere الحالي، خذ نسخة احتياطية ونفّذ ترحيل SQLite إلى Supabase مرة واحدة قبل توجيه Render إلى القاعدة. لا توصل نسختين من التطبيق إلى قاعدة الإنتاج أثناء الترحيل.

## التحقق

- افتح `/health` وتأكد أن مرحلة الخدمة تحمل `v1.5.4`، ثم افتح `/health/ready` ويجب أن يعيد `status: ready` وإصدار `1.5.4`.

```bash
curl -i https://YOUR-SERVICE.onrender.com/health
curl -i https://YOUR-SERVICE.onrender.com/health/ready
```

الاختبارات المحلية لا تثبت صلاحية مفاتيح Google أو توفر معرفات النماذج فعلياً؛ اختبر طلباً حقيقياً لكل نموذج قبل تفعيل المشتركين.
