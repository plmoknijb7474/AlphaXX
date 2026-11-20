# إعداد APInex وRegolo وGoogle AI Studio في AlphaX v1.5.10

## Y5Z Coder Pro — APInex DeepSeek V4 Pro

- Base URL: `https://api.apinex.bond/v1`
- Model ID: `free/deepseek-v4-pro-0813`
- Protocol: OpenAI-compatible Chat Completions
- Reasoning: `reasoning_effort` مع `low`, `medium`, `high`
- Free route: يخضع لمستوى APInex المجاني وحدود الحساب والطلبات؛ لا يعتبر استخداماً غير محدود.
- أنشئ API key من حساب APInex وأضفه إلى Customers → المستخدم → Y5Z Coder Pro.

## AlphaX Pro — Regolo Gemma 4 31B

- Base URL: `https://api.regolo.ai/v1`
- Model ID: `gemma4-31b`
- Protocol: OpenAI-compatible Chat Completions
- Reasoning: `reasoning_effort` مع `low`, `medium`, `high`
- API keys: https://dashboard.regolo.ai/api-keys
- **Free-access condition:** الوصول المجاني قد يكون عبر فترة تجربة محدودة وحصة يومية، وليس مجانياً دائماً. لا يوجد paid fallback في إعداد AlphaX.

## AlphaX Max — Google AI Studio Gemini 3.6 Flash

- Base URL: `https://generativelanguage.googleapis.com/v1beta`
- Model ID: `gemini-3.6-flash`
- Protocol: Google Gemini native API (`generateContent` / `streamGenerateContent`)
- Thinking: `thinking_level` مع `minimal`, `low`, `medium`, `high`
- API key: https://aistudio.google.com/apikey
- النموذج يستخدم Google AI Studio مباشرة، وليس OpenRouter أو Regolo.

## إضافة المفاتيح للعملاء

لكل عميل: افتح Admin → Customers → اختر الحساب، ثم أضف مفتاح المزود الصحيح في قسم النموذج المقابل. المفاتيح مشفرة ومستقلة لكل عميل ولكل نموذج، ويمكن إضافة أكثر من مفتاح للتدوير عند فشل مفتاح. لا تضع مفاتيح العملاء في Render Environment ولا تشاركها بين العملاء.

## ترقية V11

- تبقي Y5Z Coder Pro على APInex دون تغيير.
- تبقي AlphaX Pro على Regolo دون تغيير.
- تنقل AlphaX Max من OpenRouter إلى Google AI Studio / Gemini 3.6 Flash.
- تعطل مفاتيح OpenRouter النشطة لـ AlphaX Max دون حذفها.
- تعيد تفعيل مفاتيح Google AI Studio القديمة التي عطلتها V9 بعلامة `PROVIDER_CHANGED`، إن كانت موجودة. اختبر المفاتيح القديمة واستبدل غير الصالح منها.
- تحافظ على أسماء النماذج العامة، System Prompts، منح النماذج، الاشتراكات، مفاتيح AlphaX، الدفع وسجلات الاستخدام.
- تمسح أي upstream fallback لنموذج AlphaX Max.

## اختبار API

استخدم رابط AlphaX العام ومفتاح العميل الذي يبدأ بـ `alpha_...`، وليس مفتاح المزوّد: 

```bash
curl -sS https://YOUR-SERVICE.onrender.com/v1/models \
  -H "Authorization: Bearer YOUR_ALPHAX_KEY"
```

اختبر Y5Z أو AlphaX Pro عبر `reasoning_effort`، واختبر AlphaX Max عبر `thinking_level`:

```bash
curl -sS https://YOUR-SERVICE.onrender.com/v1/chat/completions \
  -H "Authorization: Bearer YOUR_ALPHAX_KEY" \
  -H "Content-Type: application/json" \
  -d '{"model":"alphax-max","messages":[{"role":"user","content":"Hello"}],"thinking_level":"high","stream":false}'
```


## DeepSeek Reasoning Toggle في v1.5.10

يدعم Y5Z Coder Pro الآن ON/OFF مستقلاً بالإضافة إلى Low / Medium / High. بعد تحديث الخدمة، أعد تنزيل ملف إعداد OpenCode حتى يظهر خيار OFF الجديد.
