# Profilo metadata SPID validato: parametri, non hash

Data: 2026-11-10 · Stato: approvato (decisioni sotto) · Sostituisce in parte: `2026-09-22-spid-metadata-cert-versioning-design.md` (storico metadata, "Esponi", "Segna validato")

## Obiettivo

Poter cambiare la configurazione che finisce nel metadata SP (eIDAS, persona giuridica, dati ente, certificato) e **tornare in un clic alla configurazione validata da AgID**, sapendo in ogni momento se quella attuale coincide con la validata.

## Cosa conta per AgID

Gli IdP leggono il metadata SP dal registro AgID, non da `/spidSaml2/metadata`. "Validato" significa: il proxy si comporta come il documento registrato. Contano entityID, certificato, ACS (0–2, 4, 99/100) con i loro attributi, dati Organization/ContactPerson. Non contano firma, ID XML, prefissi dei namespace.

## Problemi dello schema attuale (verificati)

Indagine su stack locale con immagini v0.11.0 e confronto con lo storico di produzione.

1. **L'hash dipende dai prefissi XML.** `semantic_hash` = sha256 del testo serializzato prima della firma. pysaml2 7.5.5 (iam-proxy-italia v3.4.0, v0.10.0) non registra più `md`/`ds` all'import (`SamlBase.register_prefix` è diventato metodo d'istanza, rimossa la chiamata a livello di modulo): stesso contenuto serializzato come `ns0:`/`ns1:` invece di `md:`/`ds:` → hash diverso. In produzione: riga 2026-11-05 17:23 (`24e8170f3085`) = stessa configurazione della riga 2026-09-24 (`8672d89bbe01`, eIDAS on, PG on, cert #6), creata dal deploy di v0.10.0. Seconda produzione, stesso schema: riga 2026-11-05 17:34 (`f12493963bd0`) = configurazione validata del 2026-09-24 09:19 (`fad8b74d77f0`, eIDAS on, PG off, cert #7); la riga 2026-11-09 (PG on) è invece un cambio reale. Riavvii puri (restart satosa, config-api, down/up, con eIDAS/PG/CIE OIDC accesi): hash stabile, nessuna riga.
2. **"Esponi" di una riga non ultima blocca il metadata pubblicato.** Scrive `spid_sp_metadata_override.xml`, che `_metadata_endpoint` serve al posto del dinamico. Il file viene tolto solo esponendo l'ultima riga generata: un cambio di configurazione successivo (es. riattivo eIDAS) aggiorna DB e backend (ACS 99 usato) ma il metadata pubblicato resta quello vecchio, senza avviso. Riprodotto.
3. **"Esponi" duplica le righe.** Il ripristino dei toggle rigenera → riga nuova con lo stesso contenuto di quella esposta ma id diverso; "Validato" resta sulla riga originale e la copia non risulta validata.
4. **Il profilo salva solo 3 toggle.** Dati ente/contatti e certificato non sono nel profilo: ripristinare un XML vecchio con dati ente cambiati = pubblicato diverso dal comportamento.

## Decisioni (utente, 2026-11-10)

- Un solo profilo **validato attivo** + archivio dei validati precedenti.
- "Ripristina validato" **riattiva anche il certificato** del profilo, con conferma esplicita.
- "Esponi" **eliminato** per le righe generate automaticamente.

## Design

### 1. Prefissi fissi e impronta indipendente dalla serializzazione

- `spidsaml2.py`: registrare i prefissi standard (`md`, `ds`, `saml`, `samlp`, `xs`, `xsi`, oltre a `spid`/`fpa` già registrati) prima di creare il metadata, come faceva pysaml2 ≤ 7.5.4. Il documento pubblicato torna stabile tra versioni dell'immagine e uguale a quello validato nel 2026-09.
- Impronta (`content_hash`): calcolata in config-api sull'XML ricevuto, non più inviata da satosa. Algoritmo: parse con `defusedxml`, rimozione di `ds:Signature` e degli attributi `ID`/`validUntil`/`cacheDuration`, poi serializzazione canonica dell'albero in notazione Clark (`{namespace}tag`, attributi ordinati, testo con whitespace normalizzato). Indipendente da prefissi, firma, ID e indentazione; dipende da tutto il resto.
- `semantic_hash` inviato da satosa: ignorato (resta accettato nel payload per compatibilità durante il rolling deploy).
- Migrazione dati: ricalcolo di `content_hash` per tutte le righe esistenti con il nuovo algoritmo. Effetto in produzione: `24e8170f3085` e `8672d89bbe01` avranno la stessa impronta.

### 2. Profilo = parametri

Nuova tabella `spid_metadata_profile`:

| colonna | note |
|---|---|
| `id`, `created_at`, `label` | label libera (es. "Validato AgID 2026-09") |
| `status` | `validated` (al più uno) · `archived` |
| `cert_id` | FK `spid_cert`, `ON DELETE SET NULL`; l'eliminazione del cert del profilo validato è bloccata in `/admin/certs` |
| `cert_fingerprint` | sha256 del PEM: confronto anche quando `cert_id` è NULL (backup che esporta solo il cert attivo) |
| `org_name`, `org_display_name`, `org_url` | Organization |
| `contact_email`, `contact_phone`, `vat_number`, `ipa_code` | ContactPerson |
| `eidas_enabled`, `eidas_environment`, `legal_entity_enabled` | toggle |
| `entity_id` | solo confronto: deriva da `PROXY_HOSTNAME`/`PROXY_BASE_URL`, non ripristinabile |
| `metadata_version_id` | FK alla riga di storico del metadata generato con questi parametri (prova + diff) |
| `content_hash` | impronta di quel metadata |

`eidas_environment` non cambia il metadata SP ma determina il nodo FICEP contattato: fa parte del profilo validato (validazione QA ≠ produzione).

### 3. Stato "attuale vs validato"

Calcolato a ogni apertura della tab, due livelli:

- **Parametri**: confronto campo per campo tra impostazioni live (`ente_settings` + cert attivo + entityID) e profilo validato → elenco differenze leggibile ("eIDAS: on (validato: off)", "PEC: a@… (validato: b@…)", "Certificato: #7 (validato: #6)").
- **Documento**: impronta dell'ultimo metadata generato vs `content_hash` del profilo. Parametri uguali ma impronta diversa = cambio di codice (nuova immagine che altera il metadata): avviso distinto, da verificare prima di toccare il registro AgID.

Badge nella tab (pallino della tab e intestazione della card): "Metadata = validato" (verde) · "Diverso dal validato" (giallo, con elenco).

### 4. Azioni

- **Segna validato** (sulla configurazione attuale, non su una riga): crea il profilo dai parametri live + ultima riga di storico; il validato precedente passa ad `archived`. Conferma con il riepilogo dei parametri.
- **Ripristina validato**: applica i parametri del profilo a `ente_settings`; se `cert_id` ≠ cert attivo, conferma esplicita ("riattiva il certificato #6, generato il …") e attivazione (stessa logica di `/admin/certs` → Attiva); poi `generate_and_write` + reload. Il metadata torna generato dinamicamente: nessun file di override. Dopo il reload la tab mostra se l'impronta coincide.
- **Ripristina** su un profilo archiviato: stesso flusso, non cambia lo stato `validated`.
- Entità non ripristinabile (entityID diverso): azione bloccata con spiegazione (dipende da variabile d'ambiente dello stack).

### 5. Storico metadata

Resta come registro: una riga quando l'impronta cambia rispetto all'ultima (stesso dedup di oggi, nuova impronta). Colonne: data, cert, toggle, impronta, badge "= validato" se l'impronta coincide con quella del profilo validato (per contenuto, non per id). Azioni: Scarica XML, Elimina (non per righe referenziate da un profilo). Nessun "Esponi", nessun "Segna validato" per riga.

### 6. Metadata caricati a mano (emergenza)

Unico uso del file di override: righe `source="uploaded"`. "Esponi" resta solo lì, con avviso permanente nella tab finché il file esiste ("il metadata pubblicato è un file caricato a mano: le modifiche di configurazione NON vengono pubblicate") e azione "Torna al metadata generato" che rimuove il file.

### 7. Migrazione (Alembic: solo tabella; dati all'avvio)

I dati li sistema `normalize_metadata_history` all'avvio di config-api (idempotente, testabile su SQLite), non la migrazione.

1. Ricalcolo `content_hash` di tutte le righe di `spid_metadata_version`.
2. Riga con `is_validated=true` → profilo `validated`: toggle e cert dalla riga, dati ente da `ente_settings` attuali (lo storico non li ha). `label` = "Migrato da storico (validato il <data>)". In produzione: riga 2026-09-24 06:37, eIDAS off, PG off, cert #6.
3. File di override: rimosso (con log) se non è esposta una riga `uploaded`; `is_exposed` azzerato sulle righe generate. Riga `uploaded` esposta: file lasciato, avviso del punto 6.
4. Colonne `is_validated`/`is_exposed` di `spid_metadata_version`: rimosse in una migrazione successiva, dopo una release (rollback dell'immagine possibile).

### 8. Backup/ripristino

`spid_metadata_profile` incluso nel bundle JSON (`backup.py`), importato dopo `spid_cert` e senza id (sequence PostgreSQL). Il bundle porta solo il cert attivo e non lo storico: `cert_id` di altri cert e `metadata_version_id` vanno a NULL; resta `cert_fingerprint` per il confronto, il ripristino di un cert non presente è rifiutato.

## Fuori ambito

- Confronto con il metadata effettivamente presente sul registro AgID (scaricarlo e confrontare l'impronta): utile, possibile follow-up — il registro espone il metadata SP per entityID.
- Profili con nome multipli attivi.

## Test

- Impronta: stesso metadata con prefissi `md:`/`ns0:`, firme e ID diversi → stessa impronta; un attributo richiesto in più, un ACS in più, una PEC diversa → impronta diversa.
- Prefissi: metadata generato nel container satosa con `md:`/`ds:` (test nel container, come `test_spidsaml2.py`).
- Profilo: segna validato → cambia eIDAS e PEC → stato elenca le due differenze → ripristina → stato "= validato", nessun file di override.
- Ripristino con cert diverso: senza conferma non applica; con conferma attiva il cert del profilo.
- Migrazione su copia dello storico di produzione (4 righe sopra): impronte 2026-09-24/`8672…` e 2026-11-05/`24e8…` uguali; profilo validato creato dalla riga 06:37.
- e2e SPID (`spid-e2e.yml`): invariato, il toggle persona giuridica passa ancora da `/admin/legal-entity/toggle`.
