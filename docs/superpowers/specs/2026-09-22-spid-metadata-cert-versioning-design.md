# Storico certificati SPID e versioning metadata SPID/eIDAS

Data: 2026-09-22

## Contesto

Oggi il metadata SP SPID/eIDAS (`spidsaml2.py`, endpoint `/spidSaml2/metadata`) è generato
in-process a ogni avvio/reload di SATOSA a partire dalla config corrente (certificato attivo,
flag `ficep_enable`, flag `legal_entity_enable`). Non esiste alcuna storicizzazione: ogni
modifica (rotazione certificato, toggle eIDAS/persona giuridica) è distruttiva — non è possibile
tornare a un metadata precedente senza ripristinare manualmente tutta la config sottostante.

Il certificato SPID (`SpidCert`) viene già salvato come nuova riga a ogni rigenerazione, ma la
WebUI mostra solo l'ultimo (selezionato per `created_at` decrescente) e non offre export o
riattivazione di una riga precedente — funzionalità persa nel corso delle modifiche.

Le chiavi JWK usate da CIE OIDC (`JwkKey`) hanno già un meccanismo di selezione esplicita
(`CieConfig.jwk_federation_id` / `jwk_core_sig_id` / `jwk_core_enc_id`) e una WebUI completa
(list, generate, delete, select) — non sono in scope di questa spec.

## Obiettivo

1. Rendere non distruttiva la rotazione del certificato SPID: storico consultabile, export
   cert/chiave, possibilità di riattivare un certificato precedente.
2. Storicizzare il metadata SP SPID/eIDAS generato a ogni rigenerazione, con possibilità di:
   - esporre (servire all'endpoint pubblico) una versione diversa da quella corrispondente alla
     config live, per test non distruttivi in ambiente demo;
   - marcare una versione come "validata AgID", indipendentemente da quale sia esposta;
   - caricare manualmente un file di metadata XML e gestirlo con lo stesso meccanismo (storico,
     esposizione, validazione).

Fuori scope: CIE OIDC entity configuration (meccanismo di firma/trust chain differente, non XML
statico), retention/pulizia automatica dello storico (nessun requisito di scala esplicito, YAGNI).

## Componente A — Storico certificati SPID

### Modello

`SpidCert` (`config-api/app/models/cert.py`) aggiunge:

```python
is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
```

Migrazione Alembic: aggiunge la colonna, poi imposta `is_active = True` sulla riga con
`created_at` massimo per riga esistente (se presente), lasciando `False` altrove. Comportamento
identico a oggi finché l'admin non interagisce con la nuova UI.

Un solo `SpidCert.is_active = True` alla volta: invariante mantenuta a livello applicativo (ogni
transizione fa `UPDATE ... SET is_active=False` su tutte le righe prima di attivarne una), non a
livello di vincolo DB — coerente con il pattern già usato per `is_exposed`/`is_validated` su
`spid_metadata_version` (Componente B) e con la selezione esplicita già in uso per `JwkKey`.

### Route (`config-api/app/routes/certs.py`)

- `GET /certs` — sostituisce il redirect attuale: pagina con lista storico certificati
  (subject_dn, `created_at`, `not_valid_after`, badge "Attivo" se `is_active`), azioni per riga.
- `GET /certs/{id}/download/cert` — scarica `certificate_pem` (`Content-Type: application/x-pem-file`,
  `Content-Disposition: attachment`).
- `GET /certs/{id}/download/key` — scarica `private_key_pem`, stesso content-type, sempre dietro
  `_auth_check` (nessuna riconferma password aggiuntiva: la sessione admin è già il perimetro di
  sicurezza esistente per l'intera WebUI).
- `POST /certs/{id}/activate` — imposta `is_active=True` sulla riga richiesta (e `False` sulle
  altre), chiama `write_spid_cert` + `generate_and_write` (stesso flusso già usato da
  `/certs/generate`). Se `not_valid_after` della riga è già passato, mostra warning ma permette
  comunque l'attivazione (stesso principio "warning ma permetti" del Componente B).
- `POST /certs/generate` (esistente) — il nuovo cert creato ha `is_active=True`; prima
  dell'insert, disattiva tutte le righe esistenti.
- `POST /certs/{id}/delete` — consentito solo se `is_active=False` (409/redirect con errore
  altrimenti); nessun controllo di utilizzo da parte di `spid_metadata_version.cert_id` (righe
  storiche di metadata restano valide come riferimento anche se il cert è stato cancellato — FK
  con `ON DELETE SET NULL`).

### Selezione del certificato attivo altrove

Ogni query che oggi fa `select(SpidCert).order_by(SpidCert.created_at.desc()).limit(1)`
(`app/routes/idps.py`) e l'equivalente in `satosa_config_generator.py` passa a
`select(SpidCert).where(SpidCert.is_active == True).limit(1)`, con fallback al più recente se per
qualunque motivo nessuna riga è marcata attiva (difesa in profondità, non dovrebbe accadere dopo
la migrazione).

### Template

`certs/status.html.j2` diventa `certs/history.html.j2`: tabella storico invece di singolo
pannello, stesse info di oggi (subject DN, scadenza, alert se `days_left < 90` sul cert attivo)
più riga per riga: badge Attivo, pulsanti "Attiva", "Scarica certificato", "Scarica chiave privata"
(con `onclick="return confirm(...)"` visto che è materiale sensibile), "Elimina" (disabilitato se
attivo).

## Componente B — Storico e versioning metadata SPID/eIDAS

### Modello

Nuova tabella `spid_metadata_version` (`config-api/app/models/metadata_version.py`):

```python
class SpidMetadataVersion(Base):
    __tablename__ = "spid_metadata_version"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)  # "generated" | "uploaded"
    xml_content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)  # sha256 hex
    cert_id: Mapped[Optional[int]] = mapped_column(ForeignKey("spid_cert.id", ondelete="SET NULL"), nullable=True)
    is_exposed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_validated: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    label: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
```

`content_hash = sha256(xml_content)`, usato per dedupe (vedi sotto). `cert_id` è `NULL` per le
righe `source="uploaded"` (nessun certificato di riferimento gestito da questo repo).

### Snapshot automatico ad ogni rigenerazione

`spidsaml2.py` (SATOSA), in `__init__`, dopo `self.xmldoc = self.__create_metadata(self.sp.config)`,
invia un POST fire-and-forget (stesso pattern di `access_log_reporter.py`: rete Docker interna,
nessuna auth, errori non bloccanti) a un nuovo endpoint interno:

```
POST http://config-api:8000/internal/spid-metadata-snapshot
{ "xml_content": "<...>" }
```

Nuovo endpoint `config-api/app/routes/internal.py`:

```python
@router.post("/internal/spid-metadata-snapshot")
async def log_metadata_snapshot(entry: MetadataSnapshotEntry, db: AsyncSession = Depends(get_db)):
    try:
        content_hash = hashlib.sha256(entry.xml_content.encode()).hexdigest()
        last = await db.execute(
            select(SpidMetadataVersion)
            .where(SpidMetadataVersion.source == "generated")
            .order_by(SpidMetadataVersion.created_at.desc())
            .limit(1)
        )
        last_row = last.scalar_one_or_none()
        if last_row is None or last_row.content_hash != content_hash:
            active_cert = await db.execute(select(SpidCert).where(SpidCert.is_active == True).limit(1))
            cert = active_cert.scalar_one_or_none()
            row = SpidMetadataVersion(
                source="generated", xml_content=entry.xml_content, content_hash=content_hash,
                cert_id=cert.id if cert else None,
                is_exposed=last_row is None,  # prima riga in assoluto: comportamento di default = live
            )
            db.add(row)
            await db.commit()
    except Exception:
        logger.error("Failed to save metadata snapshot", exc_info=True)
    return {"ok": True}
```

Dedupe: reload che non cambiano il metadata (es. aggiunta di un IdP, che non tocca `spidsaml2.py`)
non generano righe nuove. La primissima riga storicizzata in assoluto nasce con `is_exposed=True`
per non alterare il comportamento osservabile finché l'admin non interviene.

### Esposizione (quale versione viene servita)

`POST /admin/metadata/{id}/expose` (nuova route `config-api/app/routes/metadata.py`):

- imposta `is_exposed=False` su tutte le righe, `True` sulla riga `{id}`;
- se `{id}` è l'ultima riga `source="generated"` (cioè coincide con quanto SATOSA genererebbe
  comunque dal vivo): rimuove `/satosa-conf/spid_sp_metadata_override.xml` se presente — SATOSA
  torna a servire `self.xmldoc` dinamico, nessuna differenza rispetto a oggi;
  altrimenti scrive `xml_content` della riga in quel path (nessun reload/touch necessario: il file
  viene letto a ogni richiesta, vedi sotto);
- se `version.cert_id` è valorizzato e diverso dall'`id` del `SpidCert` con `is_active=True`
  corrente, la response include un warning (mostrato come banner in UI) — non blocca l'azione.

Modifica a `spidsaml2.py::_metadata_endpoint`:

```python
def _metadata_endpoint(self, context):
    override_path = "/satosa-conf/spid_sp_metadata_override.xml"
    if os.path.exists(override_path):
        with open(override_path, "rb") as f:
            return Response(f.read(), content="text/xml; charset=utf8")
    return Response(text_type(self.xmldoc).encode("utf-8"), content="text/xml; charset=utf8")
```

Lettura ad ogni richiesta (no caching in memoria): endpoint a bassissimo traffico, evita di dover
coordinare un reload uWSGI per un cambio di esposizione.

### Upload manuale

`POST /admin/metadata/upload` (form multipart o textarea paste): valida che il contenuto sia XML
ben formato con root `EntityDescriptor` (namespace `urn:oasis:names:tc:SAML:2.0:metadata`) —
nessuna validazione semantica oltre a questo, l'admin è responsabile della correttezza. Crea riga
`source="uploaded"`, `cert_id=NULL`, `is_exposed=False` (va attivata esplicitamente dallo storico,
mai automaticamente al momento dell'upload — coerente col principio "non distruttivo").

### Validazione AgID (tag informativo)

`POST /admin/metadata/{id}/validate`: imposta `is_validated=False` su tutte le righe, `True` su
`{id}`. Nessun effetto sul serving — puramente bookkeeping per sapere quale versione è stata
approvata da AgID, indipendentemente da quale sia in quel momento esposta in demo/test.

### WebUI

Nuova pagina `/admin/metadata` (`config-api/app/templates/metadata/history.html.j2`): tabella
storico (fonte generated/uploaded, data, cert usato — link a Componente A se presente, hash
troncato, badge "Esposto" / "Validato AgID"), form di upload in testa, azioni per riga: Esponi /
Segna validato / Scarica XML / Elimina (bloccato se `is_exposed` o `is_validated`).

## Rischi e note

- **Duplicazione della firma**: il repo non tenta di rigenerare né ri-firmare metadata lato
  config-api — l'unica fonte di verità per un metadata "generated" resta SATOSA stesso via
  snapshot; l'upload manuale è responsabilità dell'admin (nessuna firma applicata da questo repo).
- **Coerenza cert/metadata**: un rollback di metadata su un cert ormai ruotato produce un
  metadata con chiave pubblica non corrispondente al cert privato attivo su SATOSA (SAML
  signature/encryption falliranno lato IdP). Il warning in fase di esposizione (vedi sopra) è
  l'unica protezione — scelta deliberata per non bloccare i test non distruttivi in demo.
- **Crescita tabella**: nessuna retention automatica in questa spec (YAGNI, nessun requisito di
  scala). Le righe non più utili restano cancellabili manualmente (righe non esposte e non
  validate).
