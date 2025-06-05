# --- Builder stage: Build geth from source with debug symbols ---
FROM golang:1.23-alpine as builder

RUN apk add --no-cache git make build-base linux-headers

WORKDIR /build
RUN git clone https://github.com/ethereum/go-ethereum.git .

# Build geth with debug symbols, no optimizations, no inlining
RUN cd cmd/geth && \
    go build -gcflags "all=-N -l" -ldflags "" -o /build/geth

RUN go install golang.org/x/tools/gopls@latest

# --- Final image ---
FROM alpine:latest

RUN apk add --no-cache bash curl jq gdb python3 py3-pip go
RUN ln -sf python3 /usr/bin/python

# Copy the debug build of geth
COPY --from=builder /build/geth /usr/local/bin/geth
COPY --from=builder /go/bin/gopls /usr/local/bin/gopls
COPY --from=builder /build /build
ADD extract_calls_lsp.py /extract_calls_lsp.py
ADD extract_functions_lsp.py /extract_functions_lsp.py
ADD extract_callgraph_lsp.py /extract_callgraph_lsp.py
ADD run_all_lsp.sh /run_all_lsp.sh

# Generate the version.txt file.
RUN /usr/local/bin/geth version | head -1 > /version.txt

# Inject the startup script and dependencies
ADD geth.sh /geth.sh
COPY trace.gdb /home/ramshreyas/Documents/Dev/ETHFoundation/hive/clients/go-ethereum/trace.gdb
ADD mapper.jq /mapper.jq
RUN chmod +x /geth.sh
RUN chmod +x /run_all_lsp.sh

# Inject the enode id retriever script.
RUN mkdir /hive-bin
ADD enode.sh /hive-bin/enode.sh
RUN chmod +x /hive-bin/enode.sh

# Add a default genesis file.
ADD genesis.json /genesis.json

# Export the usual networking ports to allow outside access to the node
EXPOSE 8545 8546 8547 8551 30303 30303/udp

# Start an interactive shell and run only the call graph extraction
CMD ["/bin/bash"]
# Optionally, to run both scripts automatically, use:
# CMD ["/run_all_lsp.sh"]