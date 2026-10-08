FROM node:22-alpine AS build

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY index.html .
COPY vite.config.js .
COPY src ./src
RUN npm run build

FROM nginx:1.27-alpine AS runtime

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
