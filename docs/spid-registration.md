# Accreditamento SPID

## Prerequisiti

Stack deployato su HTTPS. Certificato SPID generato automaticamente al primo avvio.

## Procedura

### 1. Verificare il certificato SPID

WebUI → **Certificati → Stato certificato SPID**

SubjectDN conforme AgID:
```
CN=<PROXY_HOSTNAME>, O=<ORG_NAME>, 2.5.4.83=https://<PROXY_HOSTNAME>,
2.5.4.97=PA:IT-<IPA_CODE>, C=IT, L=<ORG_CITY>
```

### 2. Abilitare almeno un IdP SPID

WebUI → **Provider SPID** → abilitare almeno `spid-aruba`.

Necessario per generare il metadata SP.

### 3. Scaricare il metadata SP

```
GET https://<PROXY_HOSTNAME>/.well-known/spid-sp-metadata
```

Oppure WebUI → **Provider SPID → Scarica metadata SP**.

### 4. Validazione

Validare con [spid-saml-check](https://github.com/italia/spid-saml-check): caricare il file XML localmente (non via URL).

### 5. Invio ad AgID

Seguire procedura ufficiale AgID per Service Provider.

### 6. Abilitare IdP in produzione

Dopo approvazione AgID: WebUI → **Provider SPID** → abilitare tutti gli IdP necessari.

## Rinnovo certificato

Rinnovo automatico (cron mensile) se scade entro 90 giorni.

**Dopo ogni rinnovo**: scaricare nuovo metadata e aggiornare portale AgID.
