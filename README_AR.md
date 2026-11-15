# AlphaX v1.5.0

AlphaX is a multi-customer, OpenAI-compatible gateway backed exclusively by Google's native Gemini API / Google AI Studio. Customers use fake public aliases; provider model IDs, provider credentials and System Prompts remain server-side.

## Built-in public models

| Public alias | Google model ID | Thinking |
|---|---|---|
| Y5Z Coder Pro | `gemma-4-26b-a4b-it` | minimal / high |
| AlphaX Pro | `gemini-3.6-flash` | minimal / low / medium / high |
| AlphaX Max | `gemma-4-31b-it` | minimal / high |

The AlphaX Max mapping to Gemma 4 31B IT is the selected interpretation of the user's “other Max model” instruction. It can be changed in Admin → Models & Prompts.

## Dynamic model catalog

Admin can add any Google AI Studio model without a code change: public alias, exact Google model ID, a required independent System Prompt, reasoning levels/variants, request defaults, fallback model IDs, tools/streaming/vision support, description, skills and image. Each customer receives separate Google key credentials per model, with failover only among that customer's own active keys.

## Supabase

Use `python scripts/configure_supabase.py` from Bash. It prompts for the Supabase PostgreSQL URI with hidden input, tests SSL connectivity, rejects a non-empty `public` schema, backs up `.env`, and writes `DATABASE_URL` only after successful validation. Then preview and apply the SQLite migration with `scripts/migrate_sqlite_to_supabase.py`. Keep the original SQLite database and current `SECRET_KEY` / `FERNET_KEY`. PythonAnywhere external PostgreSQL access requires a paid account.

## Run tests

```bash
python -m compileall -q app tests scripts
pytest -q
```


## الإصدار 1.5.4

راجع `PATCH_NOTES_V1.5.4_AR.md` لإصلاحات توافق مخطط قاعدة البيانات وأخطاء إجراءات لوحة الأدمن. الإصلاحات الإضافية تُطبّق عند بدء التطبيق بعد النشر.


## الإصدار 1.5.5

يعالج رفض أسماء المستخدمين الجديدة عند وجود تسلسل PostgreSQL متأخر، ويميّز خطأ تكرار اسم المستخدم الحقيقي عن بقية أخطاء قاعدة البيانات. راجع `PATCH_NOTES_V1.5.5_AR.md`.
