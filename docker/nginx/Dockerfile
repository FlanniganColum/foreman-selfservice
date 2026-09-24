FROM nginx:1.29-alpine
RUN apk add --no-cache openssl gettext
COPY docker/nginx/default.conf.template /etc/nginx/templates/default.conf.template
COPY docker/nginx/entrypoint.sh /docker-entrypoint.d/05-selfservice-tls.sh
RUN chmod +x /docker-entrypoint.d/05-selfservice-tls.sh
