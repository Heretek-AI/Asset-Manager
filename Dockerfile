# syntax=docker/dockerfile:1

# ---- build the native binary ----
FROM golang:1.24-bookworm AS build
WORKDIR /src/native
COPY native/go.mod ./
COPY native/*.go ./
COPY native/web/ ./web/
RUN CGO_ENABLED=0 go build -trimpath -o /out/assetmgrd .

# ---- runtime: binary + Python host ----
FROM debian:trixie-slim
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 python3-yaml git ca-certificates \
  && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY assetmgr/ ./assetmgr/
COPY anchorpoint/ ./anchorpoint/
COPY apsync/ ./apsync/
COPY actions/ ./actions/
COPY --from=build /out/assetmgrd /usr/local/bin/assetmgrd
ENV ASSETMGR_HOME=/app \
    ASSETMGR_ACTIONS=/app/actions
EXPOSE 8080
VOLUME ["/work"]
CMD ["assetmgrd", "-addr", "0.0.0.0:8080"]
