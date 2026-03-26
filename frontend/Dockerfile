FROM node:20-alpine AS build

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

ARG VITE_APP_BASE_PATH=/
ARG VITE_API_BASE=/api
ARG VITE_ADMIN_ENTRY_PATH=/ops-admin
ENV VITE_APP_BASE_PATH=$VITE_APP_BASE_PATH
ENV VITE_API_BASE=$VITE_API_BASE
ENV VITE_ADMIN_ENTRY_PATH=$VITE_ADMIN_ENTRY_PATH

RUN npm run build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
