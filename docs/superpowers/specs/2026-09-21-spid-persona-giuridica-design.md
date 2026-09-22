# SPID persona giuridica (Tipo 4 / uso professionale) — design

## Contesto e problema

L'ente vuole permettere a persone giuridiche (aziende, tramite un legale
rappresentante/dipendente delegato) di autenticarsi via SPID, oltre alle
persone fisiche standard già supportate.

SPID definisce 4 tipologie di identità digitale (non livelli di sicurezza,
concetto ortogonale a L1/L2/L3):

1. Persona fisica (cittadino, caso già supportato)
2. Persona giuridica pura (solo dati azienda, raro, non rilevante qui)
3. Uso professionale persona fisica (solo dati persona)
4. **Uso professionale per persona giuridica** — veicola sia dati persona
   fisica sia dati azienda. È questo il caso d'uso richiesto.

Verificato leggendo il codice: il nostro backend SPID (`satosa/plugins/spidsaml2.py`)
non invia mai l'estensione SAML `Purpose` nell'`AuthnRequest`. Per
specifica AgID, in assenza di questa estensione l'IdP accetta solo
identità Tipo 1 e 3 — un utente che tenta il login con identità Tipo 2/4
viene **respinto dall'IdP con errore `nr30`**, prima di arrivare al nostro
sistema. Questo è il gap reale, non il livello di sicurezza SPID.

## Fonti verificate (nessuna supposizione)

- **Avviso AgID n.18 v.2** (13/11/2020, "Autenticazione con le diverse
  tipologie di identità digitale") — meccanismo tecnico:
  `<samlp:Extensions xmlns:spid="https://spid.gov.it/saml-extensions">
  <spid:Purpose>VALORE</spid:Purpose></samlp:Extensions>` nell'`AuthnRequest`.
  Valori: *(assente)* = Tipo 1+3, `P` = Tipo 3+4, `LP` = Tipo 2+4,
  `PG` = solo Tipo 4, `PF` = solo Tipo 3, `PX` = Tipo 2+3+4. Mismatch tra
  valore dichiarato e tipo identità usata dall'utente → errore `nr30`.
- **Regolamento SPID uso professionale**, Determina AgID n. 240/2025
  (adottato 20/11/2025) — formalizza per regolamento l'obbligo, per
  **tutti** i gestori SPID accreditati, di supportare correttamente la
  verifica degli "Attributi uso professionale" (= valori Purpose) nelle
  richieste di autenticazione, entro 3 mesi dall'entrata in vigore
  (norme transitorie, §9). Nessun nuovo meccanismo tecnico rispetto
  all'Avviso 18; nessun registro/API di discovery introdotto.
- **Issue upstream `italia/iam-proxy-italia#67`** ("Accesso con spid e
  persone giuridiche", aperta, senza commenti) — conferma che il fork da
  cui deriva la nostra immagine base non implementa questo meccanismo;
  nessuna scorciatoia disponibile a monte.
- **Metadata aggregato SPID** (`registry.spid.gov.it/metadata/idp/spid-entities-idps.xml`,
  lo stesso file già scaricato dal cron `metadata_watcher.py`) — scaricato
  e ispezionato a mano: alcuni `EntityDescriptor` dichiarano
  `<spid:SupportedPurposes>` (su 12 IdP correnti, solo TeamSystem e
  EtnaHitech lo dichiarano). **Scartato come fonte di discovery**: Namirial
  offre realmente Tipo 3/4 (confermato dalla loro pagina prodotto) ma non
  dichiara `SupportedPurposes` nel metadata — la dichiarazione è opzionale
  e incompleta anche tra IdP che supportano davvero la funzionalità.
- **pysaml2** (`samlp.py` upstream, IdentityPython) — `AuthnRequestType_`
  espone `extensions` (classe `samlp.Extensions`, namespace
  `urn:oasis:names:tc:SAML:2.0:protocol`, cardinalità 0-1). Pattern reale
  d'uso di `saml2.ExtensionElement` già presente nel fork upstream
  (`backends/spidsaml2.py`, per estensioni `ContactPerson`/Avviso 29 —
  contesto diverso ma stessa classe pysaml2).
- **Sorgente SATOSA fork** (`peppelinux/SATOSA`, `backends/saml2.py`) —
  `disco_response(self, context)` chiama `self.authn_request(context, entity_id)`
  passando lo stesso oggetto `context`, senza alterare `context.request`
  oltre a leggere `entityID`. `disco_query(self, context)` (che costruisce
  il redirect verso la discovery page) è override-abile.
- **`OpenIDConnectFrontend`** (stesso fork) — durante `handle_authn_request`
  popola `context.state["OIDC"] = {"oidc_request": <querystring raw>}`,
  leggibile da qualunque backend a valle nella stessa richiesta.

## Decisione di design

Niente filtro né discovery automatica della lista IdP per il flusso
"persona giuridica": il Regolamento 240/2025 impone per legge il supporto
universale entro breve termine, quindi filtrare in base a metadata
dichiarativo (incompleto/opzionale, vedi Namirial) rischierebbe di
escludere IdP che in realtà funzionano. Si mostra sempre la lista IdP
completa; se l'IdP scelto non supporta ancora la verifica (periodo
transitorio), l'errore `nr30`/`nr08` viene gestito con messaggio chiaro
invece di un fallimento silenzioso.

## Componenti

### A — Metadata SP + pannello impostazioni

- `EnteSettings.legal_entity_enabled: bool` (nuovo campo, migration
  alembic, pattern identico a `eidas_enabled`).
- `satosa_config_generator.py`: quando `True`, aggiunge
  `optional_attributes: ["companyName", "registeredOffice", "ivaCode"]`
  dentro `sp_config["service"]["sp"]` (oggi solo `required_attributes`).
  pysaml2 usa questa chiave per popolare `AttributeConsumingService[0].requested_attribute`
  nel metadata SP pubblicato — **cambia il metadata SPID registrato**,
  richiede ri-validazione AgID (stesso pattern già documentato per eIDAS
  in `CLAUDE.md`).
- Nuova route `config-api/app/routes/legal_entity.py` (pattern
  `eidas.py`): GET pagina stato + check metadata live via
  `AttributeConsumingService`, POST toggle con `window.confirm()` di
  avviso, rigenera config + reload SATOSA dopo save.
- Nuovo template `legal_entity/config.html.j2` (pattern `eidas/config.html.j2`).
- Link nav WebUI.

### B — Wiring `Purpose` in `spidsaml2.py` (aggiornato dopo lettura diretta del file)

`authn_request()` (righe 415-430 di `satosa/plugins/spidsaml2.py`) **ha
già** un meccanismo funzionante e testato in produzione per leggere
parametri custom dalla query OIDC originale: itera `context.state.values()`
cercando un dict con chiave `"oidc_request"`, ne fa il parse con
`urllib.parse.parse_qs`, ed estrae chiavi note (oggi usato per
`attribute_consuming_service_index`/`acs_index`). Stesso identico
meccanismo riusabile per leggere lo `scope` OIDC — **non serve alcun
round-trip via disco page**, il segnale è già disponibile nello stesso
punto in cui viene costruito l'`AuthnRequest`, indipendentemente da quale
IdP l'utente ha scelto tramite la discovery page normale (invariata).

Due funzioni pure nuove (testabili in unit test isolati, senza bisogno di
un `SAMLBackend`/pysaml2 SP completamente inizializzato — pattern già
usato per `_redact_pii_xml` in questo stesso file):

```python
def _legal_entity_requested(context) -> bool:
    for v in context.state.values():
        if isinstance(v, dict) and "oidc_request" in v:
            oidc_request = v["oidc_request"]
            if not oidc_request:
                return False
            params = urllib.parse.parse_qs(oidc_request)
            scopes = params.get("scope", [""])[0].split()
            return "legal_entity" in scopes
    return False


def _build_purpose_extension(purpose: str) -> saml2.samlp.Extensions:
    ext = saml2.ExtensionElement(
        "Purpose", namespace="https://spid.gov.it/saml-extensions", text=purpose
    )
    return saml2.samlp.Extensions(extension_elements=[ext])
```

In `authn_request()`, subito dopo `authn_req.requested_authn_context = req_authn_context`
(riga 462) e prima di `client.sign(...)` (l'estensione deve rientrare
nella firma):

```python
if _legal_entity_requested(context):
    authn_req.extensions = _build_purpose_extension("PG")
```

Nessuna whitelist necessaria: l'unico valore che costruiamo è la costante
`"PG"` (Tipo 4, uso professionale per persona giuridica) — non c'è input
esterno che finisce raw nell'XML.

**Gestione errore `nr30`**: già implementata, nessuna modifica necessaria.
`SPID_ANOMALIES[30]` (riga 98 dello stesso file) contiene già messaggio e
troubleshoot corretti ("L'identità digitale utilizzata non è un'identità
digitale del tipo atteso"); `authn_response()` cattura già
`StatusAuthnFailed`, estrae il codice errore dalla `StatusMessage` IdP e
chiama `handle_spid_anomaly()` genericamente per qualunque codice. Un IdP
che rifiuta `Purpose=PG` (periodo transitorio, vedi Regolamento 240/2025)
produce automaticamente questo messaggio già corretto.

### C — Opt-in client OIDC

- Nuovo scope `legal_entity` nella checkbox list di
  `clients/form.html.j2` (oggi `openid`/`profile`/`email`), salvato in
  `OIDCClient.allowed_scopes` (array già esistente, nessuna migrazione).

### D — Flusso end-to-end (nessun toggle UI, nessun filtro IdP)

Non è una fase separata: è la composizione di B+C. Nessuna modifica a
`disco.html`/`disco_query`/UI — la discovery page resta identica a oggi.

1. Client fa `/authorize?scope=openid profile legal_entity`.
2. Utente sceglie un IdP dalla discovery page normale, invariata.
3. `authn_request()` (pezzo B) rileva lo scope `legal_entity` nella
   richiesta OIDC originale (stesso meccanismo di `acs_index`, già in
   produzione) e aggiunge `Purpose=PG` all'`AuthnRequest`, qualunque sia
   l'IdP scelto.
4. Se l'IdP supporta Tipo 4 → login riuscito, claim azienda esposti
   nell'id_token (già implementato, PR #23).
5. Se l'IdP non supporta ancora (periodo transitorio) → errore `nr30`
   gestito automaticamente con messaggio chiaro (già esistente, pezzo B).

## Testing

- Unit test `test_satosa_config_generator.py`: `legal_entity_enabled` →
  `optional_attributes` presenti/assenti (pezzo A), scope `legal_entity`
  in `allowed_scopes` (pezzo C).
- Test WebUI pattern `test_eidas.py` per il nuovo pannello (pezzo A).
- Unit test isolati (pattern `test_redact_pii_xml_*` in
  `satosa/tests/test_spidsaml2.py`, nessun SP pysaml2 completo richiesto):
  `_legal_entity_requested()` con context fittizio (scope con/senza
  `legal_entity`, oidc_request assente), `_build_purpose_extension()`
  contro l'XML atteso dall'Avviso 18 (confronto stringa/parsing).
- Wiring completo in `authn_request()` (l'integrazione dei due pezzi sopra
  dentro il flusso reale) resta coperto solo dalla suite di integrazione
  esistente (build immagine + pytest nel container, vedi `CLAUDE.md`) —
  non richiede nuova fixture, il file `test_spidsaml2.py` dichiara già
  esplicitamente `authn_request` fuori scope per unit test.

## Rischi e note aperte

- Attivare il toggle A richiede ri-validazione AgID del metadata SPID —
  comunicare all'operatore, non automatizzabile da questo sistema.
- La copertura end-to-end di `authn_request()` con `Purpose` reale resta
  verificabile solo manualmente/in integrazione (nessuna fixture SP
  completa in questo repo, per scelta preesistente documentata nel file
  di test).
