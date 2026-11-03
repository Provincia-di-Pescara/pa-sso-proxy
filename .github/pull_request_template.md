## Cosa cambia

<!-- Breve descrizione e motivazione. Issue collegata: #… -->

## Impatto

- [ ] Tocca SPID/CIE (plugin, `spidsaml2.py`, metadata SP, librerie di firma) → verificato login sul validator / collaudo CIE
- [ ] Modifica il metadata SPID (nuovo ACS, eIDAS, persona giuridica) → serve ri-validazione AgID
- [ ] Migrazione Alembic
- [ ] Nuova variabile d'ambiente (aggiornati `.env.example` e `docs/deployment.md`)
- [ ] Nuova Action di terze parti (aggiunta all'elenco consentito **prima** del merge, pin per SHA)
- [ ] Nuova dipendenza pip (solo nei `.in`, lock rigenerati con `scripts/compile-requirements.sh`)

## Verifica

<!-- Test eseguiti (pytest config-api, test nel container satosa, smoke-stack, prova manuale). -->

## Note per il rilascio

<!-- Azioni manuali in produzione (Portainer, variabili, registro AgID/CIE), se servono. -->
