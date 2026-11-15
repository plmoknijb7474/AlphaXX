# إعداد AlphaX باستخدام Render PostgreSQL الداخلي

هذه الحزمة تضبط نشر AlphaX على Render ليستخدم **Render PostgreSQL** عبر الشبكة الخاصة، بدلاً من Supabase. التطبيق يستخدم SQLAlchemy وPostgreSQL/psycopg بالفعل؛ لا يحتاج إلى تغيير طبقة قاعدة البيانات.

## مهم قبل التبديل

- تغيير `DATABASE_URL` إلى قاعدة Render جديدة يجعل التطبيق يبدأ على قاعدة مختلفة وفارغة.
- هذا لا ينسخ بيانات Supabase. إذا كان لديك مستخدمون أو اشتراكات أو مفاتيح Google مشفرة أو سجلات دفع في Supabase، فلا تبدّل `DATABASE_URL` قبل نقل البيانات.
- احتفظ بقيمة `FERNET_KEY` الحالية نفسها؛ المفاتيح المشفرة في قاعدة البيانات لا يمكن فكها بمفتاح مختلف.
- لا تحذف Supabase إلى أن تتأكد من اكتمال النقل والتحقق من الحسابات والاشتراكات.

## 1. إنشاء قاعدة Render PostgreSQL

1. افتح Render Dashboard.
2. اضغط **New + → PostgreSQL**.
3. الاسم المقترح: `alphax-db`.
4. اختر المنطقة **Frankfurt** لتطابق خدمة `alphax-api` الحالية.
5. اختر الخطة المناسبة لك، ثم أنشئ قاعدة البيانات.

### تنبيه حول الخطة المجانية

قاعدة Render PostgreSQL المجانية محدودة بسعة 1 GB وتنتهي بعد 30 يوماً. بعد انتهاء المدة توجد مهلة 14 يوماً للترقية قبل حذف قاعدة البيانات وبياناتها. استخدمها للاختبار فقط، أو اختر خطة مدفوعة للاستخدام المستمر.

## 2. الحصول على رابط الاتصال الداخلي

1. افتح قاعدة `alphax-db` في Render.
2. افتح **Connect**.
3. انسخ **Internal Database URL**، وليس External Database URL.
4. يجب أن تكون قاعدة البيانات وخدمة AlphaX في نفس Workspace والمنطقة حتى يعمل الاتصال الداخلي.

## 3. ربط خدمة AlphaX الحالية

1. افتح خدمة `alphax-api` في Render.
2. افتح **Environment**.
3. ابحث عن المتغير `DATABASE_URL`.
4. استبدل قيمته برابط **Internal Database URL** الذي نسخته.
5. احفظ التغيير واختر إعادة النشر إذا لم يبدأ Render النشر تلقائياً.

لا تضع رابط قاعدة البيانات في GitHub أو داخل ملفات المشروع. ضعه في Environment على Render فقط.

## 4. ما الذي يحدث عند أول تشغيل؟

عندما تكون قاعدة Render فارغة، يقوم AlphaX عند بدء التشغيل بإنشاء جداول النظام والخطط الافتراضية وحساب الأدمن من المتغيرين:

- `ADMIN_USERNAME`
- `ADMIN_PASSWORD`

تُنشأ قاعدة جديدة؛ لا تنتقل إليها بيانات Supabase القديمة تلقائياً.

## 5. متغيرات البيئة

احتفظ بكل متغيرات البيئة الموجودة حالياً. غيّر `DATABASE_URL` فقط عند اعتماد قاعدة Render الجديدة. لا تغيّر:

- `SECRET_KEY`
- `FERNET_KEY`
- `ADMIN_PASSWORD`
- `ADMIN_USERNAME`
- `PUBLIC_BASE_URL`
- `COOKIE_SECURE`
- `DAILY_QUOTA_TIMEZONE`
- `PAYMENT_REVIEW_TIMEZONE`

## 6. التحقق بعد النشر

افتح الرابطين التاليين مع استبدال اسم الخدمة:

```bash
curl -i https://YOUR-SERVICE.onrender.com/health
curl -i https://YOUR-SERVICE.onrender.com/health/ready
```

يجب أن تكون نتيجة `/health/ready` بحالة `ready`، وأن يظهر إصدار AlphaX `1.5.6`.

بعد ذلك اختبر:

1. تسجيل الدخول إلى الأدمن.
2. إنشاء حساب مستخدم تجريبي.
3. إنشاء خطة أو فتح صفحة الخطط.
4. فتح لوحة المستخدمين.

راجع Render Logs بعد كل اختبار. إذا ظهر `Internal Server Error`، أرسل أول traceback كامل من السجل من دون أي كلمات مرور أو روابط اتصال.

## 7. نقل بيانات Supabase الحالية

إذا كانت لديك بيانات حالية تريد الاحتفاظ بها، لا تغيّر `DATABASE_URL` إلى قاعدة Render الفارغة الآن. يجب أولاً أخذ نسخة احتياطية ونقل الجداول والصفوف مع الحفاظ على المعرفات والعلاقات، ثم مزامنة PostgreSQL sequences، ثم اختبار تسجيل الدخول والاشتراكات ومفاتيح API. أبقِ Supabase كما هو إلى أن يكتمل النقل والتحقق.

## مراجع Render الرسمية

- إنشاء وربط PostgreSQL: https://render.com/docs/postgresql-creating-connecting
- الشبكة الخاصة: https://render.com/docs/private-network
- الخطط المجانية وحدودها: https://render.com/docs/free
