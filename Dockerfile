# syntax=docker/dockerfile:1

# ---- build the native binary ----
FROM golang:1.24-bookworm AS build
WORKDIR /src/native
COPY native/go.mod ./
COPY native/*.go ./
COPY native/web/ ./web/
RUN CGO_ENABLED=0 go build -trimpath -o /out/assetmgrd .

# ---- runtime: binary + Python host + headless Godot ----
FROM debian:trixie-slim
ARG GODOT_VERSION=4.3-stable
RUN apt-get update \
  && apt-get install -y --no-install-recommends python3 python3-yaml git ca-certificates curl unzip \
  && rm -rf /var/lib/apt/lists/* \
  && curl -sL -o /tmp/godot.zip "https://github.com/godotengine/godot/releases/download/${GODOT_VERSION}/Godot_v${GODOT_VERSION}_linux.x86_64.zip" \
  && unzip -q /tmp/godot.zip -d /tmp/godot-unzip \
  && mv /tmp/godot-unzip/Godot_v*_linux.x86_64 /usr/local/bin/godot \
  && chmod +x /usr/local/bin/godot \
  && rm -rf /tmp/godot.zip /tmp/godot-unzip
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
