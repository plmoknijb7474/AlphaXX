# نشر AlphaX v1.5.10 على Render

هذه الحزمة مهيأة لخدمة Render Web Service باستخدام Docker وFastAPI/Uvicorn.

## إعداد الخدمة

- Runtime: Docker
- Root Directory: اتركه فارغاً إذا كان Dockerfile في جذر المستودع
- Build Command: فارغ
- Start Command: فارغ؛ Dockerfile يشغّل Uvicorn
- Health Check Path: `/health/ready`
- المنطقة: Frankfurt لخدمة `alphax-api` وقاعدة البيانات

## متغيرات Environment

احتفظ بمتغيرات Render الحالية كما هي: `ENVIRONMENT`, `APP_NAME`, `COOKIE_SECURE`, `ADMIN_USERNAME`, `SECRET_KEY`, `FERNET_KEY`, `ADMIN_PASSWORD`, `DATABASE_URL`, `PUBLIC_BASE_URL`, `DAILY_QUOTA_TIMEZONE`, `PAYMENT_REVIEW_TIMEZONE`. لا تغيّر `SECRET_KEY` أو `FERNET_KEY` أو `DATABASE_URL` في هذا التحديث. لا تضف مفاتيح العملاء إلى Environment.

## توزيع النماذج v1.5.10

| النموذج | المزوّد | المعرّف الداخلي | التفكير |
|---|---|---|---|
| Y5Z Coder Pro | APInex | `free/deepseek-v4-pro-0813` | ON/OFF + low / medium / high |
| AlphaX Pro | Regolo | `gemma4-31b` | low / medium / high |
| AlphaX Max | Google AI Studio | `gemini-3.6-flash` | minimal / low / medium / high |

## ترقية V12 — DeepSeek Reasoning ON/OFF

تضيف الترقية مفتاحاً مستقلاً لإيقاف التفكير في Y5Z Coder Pro. خيار OFF يرسل `thinking: {"type":"disabled"}` إلى مسار APInex؛ وعند ON ترسل قيمة `reasoning_effort` المختارة من Low / Medium / High. لا تؤثر الترقية على AlphaX Pro أو AlphaX Max أو المفاتيح أو الاشتراكات أو System Prompts.

## ترقية V11

بعد أول تشغيل، تنفذ ترقية V11 مرة واحدة: تنقل AlphaX Max فقط من OpenRouter إلى Google AI Studio. تعطّل مفاتيح OpenRouter النشطة دون حذفها، وتعيد تفعيل مفاتيح Google القديمة التي تحمل علامة `PROVIDER_CHANGED` من ترقية V9. تظل Y5Z على APInex وAlphaX Pro على Regolo. لا تحذف الترقية المستخدمين أو الاشتراكات أو الدفع أو الاستخدام أو System Prompts أو منح النماذج أو مفاتيح AlphaX.

## إضافة مفاتيح المزوّد

1. Y5Z Coder Pro: أضف مفتاح APInex في لوحة Customers → الحساب → Y5Z Coder Pro.
2. AlphaX Pro: أنشئ مفتاحاً من [Regolo API Keys](https://dashboard.regolo.ai/api-keys) وأضفه تحت AlphaX Pro. الوصول إلى Gemma على Regolo يخضع لحصص التجربة/الخطة.
3. AlphaX Max: أنشئ مفتاحاً من [Google AI Studio API Keys](https://aistudio.google.com/apikey) وأضفه تحت AlphaX Max.

لا تضع مفتاحاً عاماً مشتركاً في Render Environment؛ المفاتيح تُضاف لكل عميل ونموذج وتُخزن مشفرة.

## التحقق

```bash
curl -i https://YOUR-SERVICE.onrender.com/health
curl -i https://YOUR-SERVICE.onrender.com/health/ready
```

يجب أن يعرض `/health/ready` الحالة `ready` والإصدار `1.5.10`. بعد النشر أعد تنزيل إعداد OpenCode من صفحة الحساب. اختبر Y5Z مع Reasoning OFF ثم ON على المستويات Low / Medium / High، وبعدها اختبر النموذجين الآخرين كلّاً على حدة. لا يمكن اعتبار اختبار المزوّد حياً ناجحاً قبل وضع مفاتيح صحيحة وتجربتها.
