FROM python:3.14-slim

WORKDIR /app

# Data del giorno passata dalla CI (build-arg): invalida la cache del layer di
# upgrade dei pacchetti di sistema almeno una volta al giorno. Senza, la cache
# GHA riusa il layer vecchio e le patch OS (es. libexpat) non arrivano finché
# non cambia l'immagine base.
ARG PKG_REFRESH=
RUN echo "pkg refresh: ${PKG_REFRESH}" && apt-get update -qq && apt-get upgrade -y -qq && apt-get install -y -qq curl && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    # pip non serve a runtime (solo uvicorn nel CMD) — lo rimuoviamo insieme al suo
    # bundle vendorizzato interno (pip/_vendor/), che porta con se' copie di setuptools/
    # msgpack in versioni vulnerabili (CVE-2025-47273, GHSA-6v7p-g79w-8964) non ancora
    # aggiornate upstream in nessuna release pip disponibile (verificato: pip --upgrade
    # e' gia' l'ultima, 26.2.1). Eliminarlo fisicamente e' meglio di ignorare lo scan.
    && python -m pip uninstall -y pip setuptools

COPY . .

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
