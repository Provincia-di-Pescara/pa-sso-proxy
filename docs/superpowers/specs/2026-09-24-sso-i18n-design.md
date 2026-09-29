# Internazionalizzazione delle pagine utente del proxy (IT/EN/FR/DE/ES)

Data: 2026-09-24

## Contesto

Le pagine che il cittadino vede durante il login sono solo in italiano:

- **Discovery page** (`satosa/public/static/disco.html`): tutti i testi sono hardcoded
  nell'HTML. Il selettore `IT | EN` in testata è **decorativo** (nessun handler JS). La pagina
  carica sempre `/static/locales/eid-it.json`, anche se config-api genera già
  `eid-en.json` (`satosa_config_generator.py`, `locales/eid-{lang}.json`) con titoli, footer e
  descrizioni CIE/SPID/eIDAS in inglese.
- **Pagina di errore del proxy** (`satosa/public/templates/spid_login_error.html`): titoli,
  pulsanti ("Riprova ad accedere", "Annulla") e messaggio in italiano.
- **Messaggi di errore dei backend**: `SPID_ANOMALIES` e le altre chiamate `handle_error` in
  `satosa/plugins/spidsaml2.py` (17 messaggi), `LEGAL_ENTITY_SPID_ONLY_ERROR`, gli errori del
  callback CIE (`cieoidc-endpoints/authorization_callback_endpoint.py`: annullato, timeout,
  generico). Gli stessi testi finiscono anche nell'`error_description` del redirect OIDC verso
  il client.

Il proxy serve anche utenti stranieri (eIDAS) e, con SPID, cittadini non italofoni residenti.

## Obiettivo

1. Pagine utente del proxy disponibili in **italiano, inglese, francese, tedesco, spagnolo**.
2. **Lingua scelta automaticamente**, con possibilità per l'utente di cambiarla; la scelta vale
   per tutto il flusso (discovery → eventuale pagina di errore).
3. Un'unica fonte di verità per le traduzioni, con un test che impedisce chiavi mancanti.

Fuori scope: WebUI admin (`/admin`, operatori dell'ente), pagina `/verifica` (validazione AgID),
pagine degli IdP SPID/CIE/eIDAS (non sotto il nostro controllo), valori dei claim OIDC.

## Lingue supportate e fallback

- Supportate: `it`, `en`, `fr`, `de`, `es`. Default e fallback finale: `it`.
- Una chiave mancante in una lingua ricade su `en`, poi su `it` (a runtime), ma il test di
  completezza (vedi Test) fa fallire la CI se manca una chiave: il fallback è solo una rete di
  sicurezza.
- Matching per lingua primaria: `fr-CA`, `de-AT`, `es-419` → `fr`, `de`, `es`.

## Risoluzione automatica della lingua

Ordine di precedenza, identico lato server e lato client:

1. **Scelta esplicita dell'utente**: cookie `sso_lang` (`Path=/`, `SameSite=Lax`, `Secure`,
   durata 1 anno), impostato dal selettore della discovery page. Leggibile sia dal JS sia dai
   plugin SATOSA, quindi la pagina di errore resa lato server segue la scelta fatta nella
   discovery.
2. **`ui_locales` della richiesta OIDC** del client (parametro standard OpenID Connect Core,
   lista separata da spazi in ordine di preferenza): il client può imporre la lingua della sua
   applicazione. Lato server si legge dall'`oidc_request` nello stato SATOSA (stesso meccanismo
   di `_legal_entity_requested`); verso la discovery statica viene passato come parametro
   `lang=<codice>` aggiunto da `SpidSAMLBackend.disco_query` (stesso pattern di
   `legal_entity=1`).
3. **Lingua del browser**: `Accept-Language` (con pesi `q`) lato server, `navigator.languages`
   lato client.
4. `it`.

Implementazione:

- **Server**: nuovo modulo `satosa/plugins/i18n.py` (copiato in `/satosa_proxy/backends/i18n.py`)
  con `resolve_lang(context) -> str` e `t(lang, key, **params) -> str`. Usato da `spidsaml2.py`
  e dai plugin CIE. Legge cookie e header da `context.http_headers` (`HTTP_COOKIE`,
  `HTTP_ACCEPT_LANGUAGE`).
- **Client** (`disco.html`): stessa logica in JS: cookie `sso_lang` → query `lang` →
  `navigator.languages` → `it`.

## Fonte delle traduzioni

Un file JSON per lingua: `satosa/public/static/i18n/{it,en,fr,de,es}.json`, chiavi piatte
con namespace:

```json
{
  "disco.title": "Entra nell'area riservata",
  "disco.spid.description": "SPID, il Sistema Pubblico di Identità Digitale, ...",
  "disco.legal_entity.note": "Accesso per conto di un'impresa. ...",
  "error.title.generic": "Non è stato possibile completare l'accesso",
  "error.button.retry": "Riprova ad accedere",
  "error.spid.19": "Autenticazione fallita per ripetuta sottomissione di credenziali errate",
  "error.legal_entity_spid_only": "L'accesso per conto di un'impresa è disponibile solo con SPID."
}
```

- Servito come statico (`/static/i18n/<lang>.json`) alla discovery page **e** letto dai plugin
  server da `/satosa_proxy/static/i18n/` — una sola fonte per client e server.
- Nuova riga `COPY public/static/i18n/ /satosa_proxy/static/i18n/` nel `satosa/Dockerfile`.
- I testi dei pulsanti SPID/CIE/eIDAS usano le traduzioni ufficiali dei kit AgID/Ministero
  dove esistono; per le altre stringhe le traduzioni sono proposte in questa implementazione e
  **vanno riviste da un madrelingua** prima del rilascio (vedi Decisioni aperte).

### Dati dell'ente (`eid-{lang}.json`)

`config-api` genera oggi `eid-it.json` e `eid-en.json`. Viene esteso a tutte e 5 le lingue:

- `header.region_name` (nome ente) e URL (logo, privacy, accessibilità, supporto) sono gli
  stessi per tutte le lingue — i dati dell'ente non vengono tradotti.
- Titoli, footer e descrizioni CIE/eIDAS oggi duplicati in `_it`/`_en` dentro
  `satosa_config_generator.py` si spostano nei file `i18n/<lang>.json`; `eid-<lang>.json`
  resta solo per i dati dinamici (nome ente, URL, login URL CIE/eIDAS, versione).

## Discovery page

- Ogni testo statico riceve un attributo `data-i18n="<chiave>"` (o `data-i18n-attr` per
  `alt`/`aria-label`); uno script applica il dizionario della lingua risolta al caricamento.
- Il selettore `IT | EN` diventa un selettore a 5 lingue (pulsanti `IT EN FR DE ES` in testata,
  ognuno con `lang` e `aria-pressed`), che imposta il cookie `sso_lang`, aggiorna
  `<html lang>` e ritraduce la pagina senza ricaricarla.
- Il cambio lingua ricarica anche `eid-<lang>.json`.
- Avviso persona giuridica, tab e lista IdP SPID inclusi. I nomi dei gestori SPID non si
  traducono.

## Pagina di errore e messaggi dei backend

- `spid_login_error.html` usa `t(lang, ...)` per titoli e pulsanti; imposta `<html lang>`.
- I messaggi passano da **testo** a **chiave**: `SPID_ANOMALIES[19]` → `"error.spid.19"`, idem
  per `LEGAL_ENTITY_SPID_ONLY_ERROR` e per gli errori CIE (`error.cie.cancelled`,
  `error.cie.timeout`, `error.cie.generic`). `handle_error` risolve la lingua dal `context` e
  traduce.
- I dettagli tecnici dinamici (messaggi del validatore SAML, eccezioni) **non** si traducono:
  restano nel campo `troubleshoot`/codice errore come oggi; il messaggio principale mostrato è
  quello generico tradotto.
- Redirect OIDC verso il client in caso di errore: `error` (codice OAuth, es. `access_denied`)
  invariato; `error_description` nella lingua risolta (tipicamente quella di `ui_locales` del
  client). I client non devono basarsi sul testo di `error_description`.

## Documentazione

- `CLAUDE.md`: regola di risoluzione della lingua, posizione dei file di traduzione, "aggiungi
  una chiave in tutte e 5 le lingue".
- Prompt/guida per i client: parametro `ui_locales` per forzare la lingua.

## Test

- **Completezza**: test (nel job `pytest` di config-api o satosa) che carica i 5 JSON e
  verifica stesso insieme di chiavi, nessun valore vuoto, stessi placeholder `{...}` per chiave.
- **Copertura chiavi**: ogni `data-i18n` presente in `disco.html` e ogni chiave usata nei
  plugin (`error.*`) esiste nei JSON.
- **`resolve_lang`** (test nell'immagine satosa): precedenza cookie > `ui_locales` >
  `Accept-Language` (pesi `q`, varianti regionali) > `it`; valori non supportati ignorati.
- **`disco_query`**: aggiunge `lang=` quando c'è `ui_locales`, insieme a `legal_entity=1`.
- **Pagina di errore**: rendering in ogni lingua con `<html lang>` corretto; messaggi
  `SPID_ANOMALIES` tradotti.
- **Generatore**: `eid-<lang>.json` generato per le 5 lingue.
- **Manuale**: discovery ed errore a video in tutte le lingue, flusso cittadino e persona
  giuridica, cambio lingua dal selettore che persiste fino alla pagina di errore.

## Decisioni aperte

1. **Revisione delle traduzioni**: chi rivede FR/DE/ES prima del rilascio? Proposta: rilascio
   con traduzioni marcate "da revisionare" nel changelog, revisione madrelingua successiva.
2. **Selettore**: 5 pulsanti in testata (proposta) oppure menu a tendina (più compatto su
   mobile).
3. **`/verifica`**: resta solo in italiano (proposta: sì, è per la validazione AgID).
