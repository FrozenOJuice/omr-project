FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .

FROM build AS test
CMD ["npm", "test"]

FROM build AS release
RUN npm run build -- --configuration production

FROM nginx:alpine
COPY --from=release /app/dist/frontend/browser /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]