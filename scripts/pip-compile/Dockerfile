# Immagine Python 3.12 usata SOLO da scripts/compile-requirements.sh per i lock
# satosa (venv 3.12 dell'immagine iam-proxy-italia). Non viene costruita:
# lo script legge tag+digest da questa riga FROM. Digest fisso, aggiornato da
# dependabot (stessa minor: il cambio 3.12 → 3.13 va fatto insieme a upstream).
FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b
# Non costruita (vedi sopra): USER solo per coerenza con la regola Trivy DS-0002.
USER 65534
