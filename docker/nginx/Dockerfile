FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend

COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./

ARG VITE_APP_BASE_PATH=/
ARG VITE_API_BASE=/api
ENV VITE_APP_BASE_PATH=$VITE_APP_BASE_PATH
ENV VITE_API_BASE=$VITE_API_BASE

RUN npm run build

FROM nginx:1.27-alpine

COPY --from=frontend-build /app/frontend/dist /usr/share/nginx/html
COPY docker/nginx/start.sh /usr/local/bin/start-nginx

RUN chmod +x /usr/local/bin/start-nginx && rm -f /etc/nginx/conf.d/default.conf

EXPOSE 80 443

CMD ["/usr/local/bin/start-nginx"]
