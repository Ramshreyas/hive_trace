# --- Builder stage: Build geth from source with debug symbols ---
FROM golang:1.23-alpine as builder

RUN apk add --no-cache git make build-base linux-headers graphviz

WORKDIR /build
RUN git clone https://github.com/ethereum/go-ethereum.git .

# Build geth with debug symbols, no optimizations, no inlining
RUN cd cmd/geth && \
    go build -gcflags "all=-N -l" -ldflags "" -o /build/geth

# Install go-callvis tool
RUN go install github.com/ofabry/go-callvis@latest

# Ensure Go modules are downloaded
RUN cd cmd/geth && go mod download

# Generate the call graph for geth main package using go-callvis
RUN cd cmd/geth && go-callvis -nostd -format dot -file /build/geth_callgraph.dot github.com/ethereum/go-ethereum/cmd/geth

# Show first lines and check if the file exists
RUN ls -lh /build/geth_callgraph.dot && head -20 /build/geth_callgraph.dot || echo "callgraph.dot is missing or empty"

# --- Final image ---
FROM alpine:latest

RUN apk add --no-cache bash curl jq gdb

# Copy the debug build of geth and the call graph
COPY --from=builder /build/geth /usr/local/bin/geth
COPY --from=builder /build/geth_callgraph.dot /geth_callgraph.dot

# Generate the version.txt file.
RUN /usr/local/bin/geth version | head -1 > /version.txt

# Inject the startup script and dependencies
ADD geth.sh /geth.sh
COPY trace.gdb /home/ramshreyas/Documents/Dev/ETHFoundation/hive/clients/go-ethereum/trace.gdb
ADD mapper.jq /mapper.jq
RUN chmod +x /geth.sh

# Inject the enode id retriever script.
RUN mkdir /hive-bin
ADD enode.sh /hive-bin/enode.sh
RUN chmod +x /hive-bin/enode.sh

# Add a default genesis file.
ADD genesis.json /genesis.json

# Export the usual networking ports to allow outside access to the node
EXPOSE 8545 8546 8547 8551 30303 30303/udp

# Output the call graph and exit
ENTRYPOINT ["/bin/sh", "-c", "cat /geth_callgraph.dot"]