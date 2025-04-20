FROM rust:slim as builder

# Install build dependencies
RUN apt-get update -y && apt-get install -y bash curl git pkg-config libssl-dev jq clang libclang-dev make

# Clone reth source from GitHub for reproducible builds
ARG RETH_REF=main
RUN git clone https://github.com/paradigmxyz/reth.git /reth-source \
    && cd /reth-source \
    && git checkout $RETH_REF

# Copy scripts and configs
COPY genesis.json /genesis.json
COPY mapper.jq /mapper.jq
COPY reth.sh /reth.sh
RUN chmod +x /reth.sh
COPY enode.sh /hive-bin/enode.sh
RUN chmod +x /hive-bin/enode.sh

# Set working directory to reth source for cargo build
WORKDIR /reth-source

# Build reth with debug symbols (for tracing PoC)
RUN RUSTFLAGS="-g" cargo build --bin reth

# Copy binary to /usr/local/bin for compatibility with scripts
RUN cp /reth-source/target/debug/reth /usr/local/bin/reth

# Create version.txt
RUN /usr/local/bin/reth --version | sed -e 's/reth \(.*\)/\1/' > /version.txt

# Phase 2: Add multi-stage build with GDB and Python
FROM debian:bookworm-slim

# Install runtime dependencies and debugging tools
RUN apt-get update -y && \
    apt-get install -y \
    bash \
    curl \
    jq \
    python3 \
    gdb \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create directory structure
RUN mkdir -p /hive-bin

# Copy from builder stage
COPY --from=builder /usr/local/bin/reth /usr/local/bin/reth
COPY --from=builder /version.txt /version.txt
COPY --from=builder /genesis.json /genesis.json
COPY --from=builder /reth.sh /reth.sh
COPY --from=builder /hive-bin/enode.sh /hive-bin/enode.sh
COPY --from=builder /mapper.jq /mapper.jq

# Phase 3: Copy GDB Python tracing script
COPY trace_instructions.py /trace_instructions.py
COPY trace_line.gdb /trace_line.gdb

# Set environment variable for tracing (can be overridden at runtime)
# Tracing is ENABLED by default in this image. Set HIVE_TRACE_INSTRUCTIONS=0 to disable GDB tracing.
ENV HIVE_TRACE_INSTRUCTIONS=1

# Export the usual networking ports
EXPOSE 8545 8546 30303 30303/udp

ENTRYPOINT ["/reth.sh"]
