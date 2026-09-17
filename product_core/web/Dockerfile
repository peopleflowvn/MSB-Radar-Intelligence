# Build UI React y như CI (`npm ci && npm run build`) rồi giữ lại đúng thư mục
# dist. Dùng cho stack độc lập ở ../../docker-compose.yml: service `web-build`
# chép dist vào volume chung để Caddy phục vụ file tĩnh và Hub đọc index.html.
FROM node:20-alpine AS build
WORKDIR /src
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM alpine:3.20
COPY --from=build /src/dist /dist
CMD ["sh", "-c", "rm -rf /out/* && cp -r /dist/. /out/"]
