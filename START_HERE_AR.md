# AlphaX v1.5.10 — ابدأ من هنا

هذا الإصدار يضيف مفتاح Reasoning ON/OFF حقيقياً إلى Y5Z Coder Pro، مع الحفاظ على مستويات Low / Medium / High وعلى جميع توجيهات النماذج الأخرى.

## التوجيه النهائي

| الاسم الظاهر | المزوّد | المعرّف الداخلي | مستويات التفكير |
|---|---|---|---|
| Y5Z Coder Pro | APInex | `free/deepseek-v4-pro-0813` | low / medium / high |
| AlphaX Pro | Regolo | `gemma4-31b` | low / medium / high |
| AlphaX Max | Google AI Studio | `gemini-3.6-flash` | minimal / low / medium / high |

## تجهيز مفاتيح API

المفاتيح مستقلة لكل عميل ولكل نموذج، وتُحفظ مشفرة في قاعدة AlphaX.

1. Y5Z Coder Pro: أضف مفتاح APInex من حساب APInex إلى Customers → المستخدم → Y5Z Coder Pro.
2. AlphaX Pro: أضف مفتاح Regolo من [لوحة مفاتيح Regolo](https://dashboard.regolo.ai/api-keys) إلى Customers → المستخدم → AlphaX Pro.
3. AlphaX Max: أضف مفتاح Google AI Studio من [Google AI Studio](https://aistudio.google.com/apikey) إلى Customers → المستخدم → AlphaX Max.
4. لا تضع مفاتيح العملاء في Render Environment أو GitHub، ولا ترسلها في المحادثة.

ترقية V11 تنقل AlphaX Max من OpenRouter إلى Google AI Studio، وترقية V12 تضيف مفتاح التفكير الحقيقي إلى Y5Z فقط. مفاتيح OpenRouter النشطة تُعطّل ولا تُحذف. مفاتيح Google AI Studio القديمة التي عطّلتها ترقية V9 تُعاد إلى التفعيل تلقائياً إن كانت ما زالت محفوظة. افحصها من لوحة العميل، واستبدل أي مفتاح قديم لا يعمل.

## مستويات التفكير

- Y5Z Coder Pro: مفتاح مستقل ON/OFF، وعند ON تتاح `low`, `medium`, `high`. عند OFF يرسل الخادم `thinking.type=disabled` ولا يخفض المستوى إلى Low.
- AlphaX Pro: `low`, `medium`, `high` عبر `reasoning_effort`.
- AlphaX Max: `minimal`, `low`, `medium`, `high`، ويرسل AlphaX قيمة `thinking_level` إلى Gemini 3.6 Flash عبر Google AI Studio.
- لا يوجد fallback إلى نموذج أو مسار مدفوع.

## المجانية والحدود

- APInex يقدّم مسار DeepSeek V4 Pro المجاني وفق حدود الحساب والمزوّد؛ تأكد من السعر الحالي في لوحة APInex قبل الاستخدام.
- Regolo يضم Gemma 4 31B ضمن فترة تجربة محدودة، وليس مجانياً دائماً.
- Google AI Studio يخضع لحصص Gemini API وحدود الحساب؛ لا تفترض أن كل الاستخدام مجاني بلا حدود.

## النشر والاختبار

- ارفع ملفات الإصدار `1.5.10` إلى فرع `main`.
- Render: Docker، واترك Build Command وStart Command فارغين.
- Health Check: `/health/ready`؛ يجب أن يعرض الإصدار `1.5.10`.
- لا تغيّر `DATABASE_URL` أو `SECRET_KEY` أو `FERNET_KEY`.
- بعد النشر، تحقق من مفاتيح Google الخاصة بـ AlphaX Max، ثم اختبر النماذج الثلاثة كلّاً على حدة ومستويات التفكير الخاصة به.

شغّل الاختبارات محلياً:

```bash
python -m compileall -q app tests scripts
python -m pytest -q
```
