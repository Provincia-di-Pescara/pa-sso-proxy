FROM nginx:alpine
# Data del giorno passata dalla CI (build-arg): invalida la cache del layer di
# upgrade dei pacchetti di sistema almeno una volta al giorno. Senza, la cache
# GHA riusa il layer vecchio e le patch OS (es. libexpat) non arrivano finché
# non cambia l'immagine base.
ARG PKG_REFRESH=
RUN echo "pkg refresh: ${PKG_REFRESH}" && apk update && apk upgrade --no-cache
RUN rm /etc/nginx/conf.d/default.conf
# Abilita 15-local-resolvers.envsh: esporta NGINX_LOCAL_RESOLVERS (da
# /etc/resolv.conf), usato dalla direttiva resolver nel template.
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1
COPY templates/proxy.conf.template /etc/nginx/templates/proxy.conf.template
