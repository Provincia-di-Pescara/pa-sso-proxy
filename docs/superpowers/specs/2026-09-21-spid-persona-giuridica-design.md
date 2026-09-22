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

### B — Wiring `Purpose` in `spidsaml2.py`

- `authn_request(self, context, entity_id)`: legge
  `purpose = context.request.get("purpose")`.
- Whitelist stretta `{None, "P", "LP", "PG", "PF", "PX"}` — valore fuori
  whitelist ignorato (query param proveniente da client esterno, mai
  passato raw a XML senza validazione).
- Costruisce l'estensione:
  ```python
  from saml2 import samlp
  purpose_ext = saml2.ExtensionElement(
      "Purpose", namespace="https://spid.gov.it/saml-extensions", text=purpose
  )
  authn_req.extensions = samlp.Extensions(extension_elements=[purpose_ext])
  ```
  Nome esatto dell'attributo (`extension_elements` vs alternativa) da
  fissare in TDD contro l'XML atteso (confronto con l'esempio letterale
  dell'Avviso 18).
- `context.request.get("purpose")` accessibile in `authn_request()` sulla
  base della lettura del sorgente `disco_response` (stesso `context`,
  nessuna cancellazione dei parametri) — **da confermare empiricamente**
  con un test d'integrazione (unico punto del design non verificato a
  runtime).
- Gestione errore `nr30`/`nr08`: estendere `handle_spid_anomaly` (già
  esistente) con messaggio dedicato quando l'anomalia deriva da un
  mismatch Purpose.

### C — Opt-in client OIDC

- Nuovo scope `legal_entity` nella checkbox list di
  `clients/form.html.j2` (oggi `openid`/`profile`/`email`), salvato in
  `OIDCClient.allowed_scopes` (array già esistente, nessuna migrazione).

### D — Flusso UI (nessun toggle, nessun filtro)

1. Client fa `/authorize?scope=openid profile legal_entity`.
2. `disco_query(self, context)` (override in `spidsaml2.py`): legge lo
   scope da `context.state["OIDC"]["oidc_request"]`; se contiene
   `legal_entity`, aggiunge `legal_entity=1` ai parametri del redirect
   verso `disco_srv` prima di chiamare `create_discovery_service_request()`.
3. `disco.html` (statico, nostro): legge `legal_entity` dalla propria
   querystring; se `1`, aggiunge `&purpose=PG` al redirect finale verso
   `/spidSaml2/disco?entityID=...` — stessa lista IdP di sempre, nessun
   filtro.
4. `authn_request()` (pezzo B) legge `purpose=PG` da `context.request`,
   costruisce l'estensione.
5. Se l'IdP scelto non supporta ancora Tipo 4 → errore `nr30`/`nr08`
   gestito con messaggio chiaro (pezzo B).

L'esposizione dei claim OIDC (`company_name`, `registered_office`,
`iva_code`) verso l'applicativo client è **già implementata** (PR #23,
mergiata) — nessun lavoro aggiuntivo su quel fronte.

## Testing

- Unit test `test_satosa_config_generator.py`: `legal_entity_enabled` →
  `optional_attributes` presenti/assenti (pezzo A), scope `legal_entity`
  in `allowed_scopes` (pezzo C).
- Test WebUI pattern `test_eidas.py` per il nuovo pannello (pezzo A).
- Test d'integrazione satosa (build immagine + pytest nel container, per
  `satosa/plugins/` — vedi `CLAUDE.md`) per: XML esatto dell'estensione
  Purpose generata (pezzo B), lettura `context.request` in
  `authn_request()` dopo `disco_response` (verifica il punto non
  confermato), redirect `disco_query` con `legal_entity=1` (pezzo D).

## Rischi e note aperte

- Nome esatto attributo pysaml2 per `extension_elements` da confermare in
  coding (TDD contro XML atteso).
- `context.request.get("purpose")` in `authn_request()` da confermare con
  test d'integrazione reale (basato su lettura sorgente, non testato a
  runtime).
- Attivare il toggle A richiede ri-validazione AgID del metadata SPID —
  comunicare all'operatore, non automatizzabile da questo sistema.
