FROM rust:slim as builder

# Install build dependencies
RUN apt-get update -y && apt-get install -y bash curl git pkg-config libssl-dev jq clang libclang-dev make

# Clone reth source code
WORKDIR /src
RUN git clone https://github.com/paradigmxyz/reth.git .

# Optionally checkout a specific commit or branch
# RUN git checkout <commit-or-branch>

# Copy scripts and configs
COPY genesis.json /genesis.json
COPY mapper.jq /mapper.jq
COPY reth.sh /reth.sh
RUN chmod +x /reth.sh
COPY enode.sh /hive-bin/enode.sh
RUN chmod +x /hive-bin/enode.sh

# Build reth with debug symbols (for tracing PoC)
RUN cargo build --release

# Copy binary to /usr/local/bin for compatibility with scripts
RUN cp /src/target/release/reth /usr/local/bin/reth

# Create version.txt
RUN /usr/local/bin/reth --version | sed -e 's/reth \(.*\)/\1/' > /version.txt

# Export the usual networking ports
EXPOSE 8545 8546 30303 30303/udp

ENTRYPOINT ["/reth.sh"]
