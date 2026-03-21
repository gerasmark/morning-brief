FROM nginx:1.27-alpine

COPY docker/nginx/start.sh /usr/local/bin/start-nginx

RUN chmod +x /usr/local/bin/start-nginx && rm -f /etc/nginx/conf.d/default.conf

EXPOSE 80 443

CMD ["/usr/local/bin/start-nginx"]
