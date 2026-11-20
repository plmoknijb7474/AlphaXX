# AlphaX v1.5.10 — إضافة Reasoning ON/OFF لـ DeepSeek V4 Pro

## Y5Z Coder Pro

- إضافة تبديل مستقل لتشغيل/إيقاف Thinking عبر OpenCode (`capabilities.reasoning.toggle`).
- عند الإيقاف، يرسل الخادم إلى APInex: `thinking: {"type":"disabled"}` ولا يحوّل OFF إلى Low.
- عند التشغيل، يرسل `thinking: {"type":"enabled"}` مع مستوى `reasoning_effort` المحدد.
- تبقى المستويات المتاحة: Low وMedium وHigh.
- لا يتغير مزود APInex أو معرف DeepSeek أو المفاتيح أو الحصص أو الاشتراكات أو صلاحيات النماذج أو System Prompt.

## بقية النماذج

- AlphaX Pro يبقى على Regolo Gemma 4 31B كما هو.
- AlphaX Max يبقى على Gemini 3.6 Flash عبر Google AI Studio كما هو.
- لم تتم إضافة مفتاح ON/OFF إلى Regolo أو Gemini.

## الترحيل

يطبق V12 ترحيل قاعدة بيانات إضافياً مرة واحدة على Y5Z فقط. لا يحذف سجلات ولا يغيّر مفاتيح المستخدمين أو بيانات الاشتراك.
