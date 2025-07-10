# Platform arguments - these are automatically populated by Docker buildx
# Provide defaults for when not using buildx
ARG BUILDPLATFORM=linux/amd64
ARG TARGETPLATFORM=linux/amd64
ARG TARGETARCH=amd64
ARG TARGETVARIANT=

ARG BUILDER_IMAGE="golang:1.24-bookworm" \
    TARGET_BASE_IMAGE="debian:12-slim" \
    BINARIES="erigon" \
    BUILD_SILKWORM="true" \
    UID_ERIGON=1000 \
    GID_ERIGON=1000

## Use xx - Dockerfile cross-compilation helpers
FROM --platform=$BUILDPLATFORM tonistiigi/xx AS xx

### Erigon Builder section:
FROM --platform=$BUILDPLATFORM ${BUILDER_IMAGE} AS builder 
ARG TARGETARCH \
    TARGETVARIANT \
    TARGETPLATFORM \
    BUILD_SILKWORM \
    BINARIES

SHELL ["/bin/bash", "-c"]

WORKDIR /erigon

## Copy all content of helpers:
COPY --from=xx / /

# Clone the repository and set up go modules
RUN git clone https://github.com/erigontech/erigon.git . && \
    xx-apt-get install -y libc6-dev g++ && \
    xx-go mod download && \
    xx-go mod tidy

RUN echo "DEBUG: building on ${TARGETARCH}${TARGETVARIANT}" && \
    if [ "x${TARGETARCH}" == "xamd64" ] && [ "x${TARGETVARIANT}" == "x" ]; then \
        echo "DEBUG: detected architecture AMD64v1"; \
        export CPU_FLAGS="GOAMD64_VERSION=v1 GOARCH=amd64"; \
    elif [ "x${TARGETARCH}" == "xamd64" ] && [ "x${TARGETVARIANT}" == "xv2" ]; then \
        echo "DEBUG: detected architecture AMD64v2"; \
        export CPU_FLAGS="GOAMD64_VERSION=v2 GOARCH=amd64"; \
    elif [ "x${TARGETARCH}" == "xarm64" ]; then \
        echo "DEBUG: detected architecture ARM64"; \
        export CPU_FLAGS="GOARCH=arm64"; \
    fi && \
    if [ "x${BUILD_SILKWORM}" != "xtrue" ] || [ "x${TARGETARCH}" == "xarm64" ] ; then \
        echo "DEBUG: add nosilkworm build tag - BUILD_SILKWORM is not true OR ARM64 architecture "; \
        export FLAG_SILKWORM=",nosilkworm"; \
    fi && \
    echo "DEBUG: Building with debug symbols - cmd - make ${CPU_FLAGS} ${BINARIES} GOBIN=/build FLAG_SILKWORM=${FLAG_SILKWORM} ." && \
    make GO=xx-go CGO_ENABLED=1 GOARCH=${TARGETARCH} ${CPU_FLAGS} ${BINARIES} GOBIN=/build BUILD_TAGS=nosqlite,noboltdb${FLAG_SILKWORM} GOBUILD_FLAGS="-gcflags 'all=-N -l' -ldflags ''" && \
    if [ "x${BUILD_SILKWORM}" == "xtrue" ] && [ "x${TARGETARCH}" == "xamd64" ]; then \
        echo "DEBUG: BUILD_SILKWORM=${BUILD_SILKWORM} - installing libsilkworm_capi.so lib on architecture AMD64"; \
        find $(xx-go env GOMODCACHE)/github.com/erigontech -name libsilkworm_capi.so -exec install {} /build \; ;\
    fi && \
    find /build -ls

### End of builder section

### Erigon Target section:
FROM debian:12-slim AS erigon
ARG TARGET_BASE_IMAGE="debian:12-slim"
ARG USER=erigon \
    GROUP=erigon \
    UID_ERIGON \
    GID_ERIGON \
    BUILD_SILKWORM \
    TARGETARCH \
    TARGETVARIANT

SHELL ["/bin/bash", "-c"]

# Copy build artifacts from builder stage
COPY --from=builder /build /tmp/build

RUN echo Installing on ${TARGETARCH} with variant ${TARGETVARIANT} && \
    addgroup --gid ${GID_ERIGON} ${GROUP} && \
    adduser --system --uid ${UID_ERIGON} --ingroup ${GROUP} --home /home/${USER} --shell /bin/bash ${USER} && \
    apt update -y && \
    apt install -y --no-install-recommends ca-certificates bash curl jq gdb python3 python3-toml && \
    apt clean && \
    rm -rf /var/lib/apt/lists/* && \
    if [ "x${TARGETARCH}" == "xamd64" ] && [ "x${BUILD_SILKWORM}" != "xfalse" ]; then \
        echo "Installing libsilkworm_capi.so library to /lib/x86_64-linux-gnu/ in case amd64 architecture:"; \
        find /tmp/build -name libsilkworm_capi.so -type f | xargs -I % install -m a=r -v % /lib/x86_64-linux-gnu/; \
        echo "Done." ; \
    fi && \    
    install -d -o ${USER} -g ${GROUP} /home/${USER}/.local /home/${USER}/.local/share /home/${USER}/.local/share/erigon && \
    echo "Installing all binaries:" && \
    shopt -s extglob && \
    for binary in '/tmp/build/!(*.so)'; do \
        install -v -o root -g root $binary /usr/local/bin/ ; \
    done

# Generate the version.txt file.
RUN /usr/local/bin/erigon --version | sed -e 's/erigon version \(.*\)/\1/' > /version.txt

# Copy the entire erigon source for debugging purposes
COPY --from=builder /erigon /erigon

# Inject the startup script and dependencies
ADD erigon.sh /erigon.sh
ADD mapper.jq /mapper.jq
RUN chmod +x /erigon.sh

# Add the gdb scripts
ADD trace.gdb /trace.gdb
ADD output/eip_breakpoints.gdb /eip_breakpoints.gdb

# Inject the enode id retriever script.
RUN mkdir /hive-bin
ADD enode.sh /hive-bin/enode.sh
RUN chmod +x /hive-bin/enode.sh

# Add genesis mapper script
COPY genesis.json /genesis.json

VOLUME [ "/home/${USER}" ]
WORKDIR /home/${USER}

USER ${USER}

# Expose networking ports
EXPOSE 8545 8546 8551 30303 30303/udp

ENTRYPOINT ["/erigon.sh"]
# ENTRYPOINT [ "/bin/bash" ]
### End of Erigon Target section
