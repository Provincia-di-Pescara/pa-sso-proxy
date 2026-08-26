FROM nginx:alpine
RUN apk update && apk upgrade --no-cache
RUN rm /etc/nginx/conf.d/default.conf
COPY conf.d/proxy.conf /etc/nginx/conf.d/proxy.conf
