# نشر AlphaX v1.5.6 على Render

هذه الحزمة معدّة لخدمة Render Web Service باستخدام Docker وFastAPI/Uvicorn، ويمكنها الاتصال بـ Render PostgreSQL عبر عنوان الاتصال الداخلي.

## الإعداد الموصى به

- Runtime: Docker
- Root Directory: فارغ إذا كان `Dockerfile` في جذر المستودع
- Build Command: فارغ
- Start Command: فارغ؛ `Dockerfile` يشغّل Uvicorn
- Health Check Path: `/health/ready`
- المنطقة: Frankfurt لخدمة `alphax-api` وقاعدة البيانات

## قاعدة البيانات

أنشئ Render PostgreSQL مستقلة من لوحة Render، ثم انسخ **Internal Database URL** من تبويب Connect، وضعه في متغير `DATABASE_URL` ضمن Environment لخدمة `alphax-api`.

استخدم Internal Database URL فقط عندما تكون خدمة AlphaX وقاعدة البيانات في نفس Workspace والمنطقة. لا تضع الرابط في GitHub ولا في ملفات المشروع.

الشرح الكامل موجود في `RENDER_POSTGRES_SETUP_AR.md`.

## متغيرات Environment

احتفظ بالمتغيرات التالية في Render:

- `ENVIRONMENT=production`
- `APP_NAME=AlphaX`
- `COOKIE_SECURE=true`
- `ADMIN_USERNAME=admin` (أو اسم الأدمن الحالي الذي تستخدمه)
- `SECRET_KEY` — قيمة قوية وفريدة
- `FERNET_KEY` — مفتاح Fernet صالح وثابت
- `ADMIN_PASSWORD` — كلمة مرور قوية
- `DATABASE_URL` — Internal Database URL من Render PostgreSQL
- `PUBLIC_BASE_URL` — رابط خدمة AlphaX الكامل على Render
- `DAILY_QUOTA_TIMEZONE=UTC`
- `PAYMENT_REVIEW_TIMEZONE=Asia/Damascus`

لا تغيّر `SECRET_KEY` أو `FERNET_KEY` عند التحديث. تغيير Fernet key قد يمنع قراءة مفاتيح المزوّد المشفرة سابقاً.

## ملاحظة حول البيانات

تغيير `DATABASE_URL` إلى قاعدة Render جديدة لا ينقل أي بيانات من Supabase. إذا كانت Supabase تحتوي حسابات أو اشتراكات أو مفاتيح أو مدفوعات، اقرأ فقرة نقل البيانات في `RENDER_POSTGRES_SETUP_AR.md` ولا تبدّل الاتصال قبل إتمام النقل.

## الخطط المجانية

خدمة الويب المجانية قد تدخل في وضع الخمول. قاعدة Render PostgreSQL المجانية محدودة بـ 1 GB وتنتهي بعد 30 يوماً، ثم توجد مهلة 14 يوماً للترقية قبل حذف البيانات. لا تستخدم قاعدة مجانية لبيانات إنتاج دائمة.

## التحقق

```bash
curl -i https://YOUR-SERVICE.onrender.com/health
curl -i https://YOUR-SERVICE.onrender.com/health/ready
```

تأكد أن الحالة `ready` وأن الإصدار `1.5.6` ظاهر. ثم اختبر تسجيل الدخول والتسجيل وصفحات لوحة الإدارة.
