# Localization

Agent Deck includes 16 languages:

| Language | Catalog / installer option |
|---|---|
| English | `en` |
| Русский | `ru` |
| Español | `es` |
| Português (Brasil) | `pt-BR` |
| Deutsch | `de` |
| Français | `fr` |
| 简体中文 | `zh-CN` |
| 繁體中文 | `zh-TW` |
| 日本語 | `ja` |
| 한국어 | `ko` |
| Bahasa Indonesia | `id` |
| Türkçe | `tr` |
| Italiano | `it` |
| Polski | `pl` |
| Українська | `uk` |
| हिन्दी | `hi` |

Fresh installations use English; `PANEL_LANGUAGE=ru` sets the server default.
On Linux this setting lives in the private `~/.config/cc-panel/env`; on macOS in
`~/.config/cc-panel/macos.json`. Reinstalling preserves the saved configuration.

**Settings → Interface language** overrides that default in the current browser,
using a one-year `cc_lang` cookie with `SameSite=Lax` (and `Secure` on HTTPS).
The login page uses the same preference. Switching languages saves session drafts
and attachment references before reloading; it does not restart agents.
Dates use the selected locale. Agent output, questions, answer choices, project
names and message drafts are never translated.

Telegram uses the language of the browser that last saved its integration settings.
This applies to pairing greetings and callback confirmations/errors, not agent questions.
Existing bot configurations without a language use the server default.

## Add a language

Copy `locales/en.json` to a BCP 47 language file such as `locales/nl.json` or
`locales/pt-PT.json`. Set `name` to the language's own name and translate values
inside `messages`; keep the source keys unchanged. The catalogs use gettext-style
source strings as keys, with numbered placeholders `{0}`, `{1}`, etc. The English
catalog provides the reference translation for the original Russian source keys.

```json
{
  "name": "Nederlands",
  "messages": {
    "Настройки": "Instellingen",
    "Скопировано: {0} симв.": "Gekopieerd: {0} tekens"
  }
}
```

Missing entries inherit English. Preserve all numbered placeholders, even if their
order changes. Catalogs are UTF-8 JSON, at most 1 MiB, with only string values.
No HTML or executable expressions are supported; translations are escaped when
rendered and interpolation parameters remain data.

The settings menu shows native language names and discovers valid catalogs
automatically. Every bundled language has a full catalog; English fallback remains
available for partial community contributions. Initial translations are generated
and checked for structural correctness and UI fit; native-speaker corrections are
welcome. Installers and the updater copy additional catalogs alongside English and
Russian. Restart the panel after editing catalogs directly because they are cached in process memory.
Run `npm run test:all` before contributing a translation.

## Documentation screenshots

Run `npm run screenshots` in a Playwright environment to regenerate the public
README images. `scripts/repo-screenshots.spec.js` supplies only synthetic demo
sessions, accounts and output; it never connects to the installed panel or bot.

## Implementation

`locales/__init__.py` loads and validates catalogs, applies English fallback,
translates static HTML text/attributes, and translates designated API status/error
fields. The server embeds a safely encoded catalog into the authenticated HTML;
the small `tr(message, parameters)` function handles dynamic UI messages.
Language selection accepts only installed catalog names, never filesystem paths.

Older updaters can install the new core before its locale package. The panel keeps
working in Russian and offers **Complete installation**; a second update repairs
the missing packages. New installers and the new updater install everything at once.
