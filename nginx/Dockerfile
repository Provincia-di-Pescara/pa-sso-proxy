FROM nginx:alpine
RUN apk update && apk upgrade --no-cache
RUN rm /etc/nginx/conf.d/default.conf
# Abilita 15-local-resolvers.envsh: esporta NGINX_LOCAL_RESOLVERS (da
# /etc/resolv.conf), usato dalla direttiva resolver nel template.
ENV NGINX_ENTRYPOINT_LOCAL_RESOLVERS=1
COPY templates/proxy.conf.template /etc/nginx/templates/proxy.conf.template
