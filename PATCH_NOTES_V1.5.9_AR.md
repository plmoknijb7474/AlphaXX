# AlphaX v1.5.9 — تصحيح توجيه AlphaX Max إلى Gemini 3.6 Flash

## التوجيه النهائي

- Y5Z Coder Pro يبقى على APInex `free/deepseek-v4-pro-0813` دون تغيير.
- AlphaX Pro يبقى على Regolo `gemma4-31b` دون تغيير.
- AlphaX Max ينتقل من OpenRouter Gemma 4 31B إلى Google AI Studio `gemini-3.6-flash`.

## التفكير

- AlphaX Max يدعم `minimal`, `low`, `medium`, `high`.
- يرسل الخادم المستوى المختار عبر Gemini API native field `generationConfig.thinkingConfig.thinkingLevel`.
- القيمة الافتراضية `medium`.

## مفاتيح العملاء

- مفاتيح OpenRouter النشطة لـ AlphaX Max تُعطّل ولا تُحذف.
- مفاتيح Google AI Studio القديمة المعطّلة بواسطة V9 والتي تحمل `PROVIDER_CHANGED` يعاد تفعيلها لاستخدامها مجدداً. يجب اختبارها أو استبدالها إذا لم تعد صالحة.
- لا تتغير مفاتيح Y5Z أو AlphaX Pro أو اشتراكات العملاء أو منح النماذج أو System Prompts أو مفاتيح AlphaX العامة.

## السلامة والتوافق

- لا يوجد upstream fallback لنموذج AlphaX Max.
- يستمر استخدام Google native API adapter، مع system instruction وتحويل الأدوات وstreaming وvision.
- لم تتم إضافة مفاتيح مشتركة إلى Environment.
