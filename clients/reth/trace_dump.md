# Instruction-Level Tracing for Ethereum Clients in Hive

This document outlines a general approach for implementing instruction-level tracing for Ethereum clients in the Hive testing framework, followed by a specific implementation example for the reth client.

---

## Table of Contents

- [General Approach](#general-approach)
  - [Core Principles](#core-principles)
  - [Architecture Overview](#architecture-overview)
  - [Implementation Requirements](#implementation-requirements)
  - [Workflow](#workflow)
  - [Debugging Tools](#debugging-tools)
- [Reth Implementation Example](#reth-implementation-example)
  - [Files Overview](#files-overview)
  - [Dockerfile Changes](#dockerfile-changes)
  - [Client Shell Script](#client-shell-script)
  - [GDB Tracing Script](#gdb-tracing-script)
  - [Usage](#usage)
  - [Output Format](#output-format)
- [Extending to Other Clients](#extending-to-other-clients)

---

## General Approach

### Core Principles

When implementing instruction tracing for Ethereum clients in Hive, the following core principles must be maintained:

1. **Separation from Test Logic**: The tracing mechanism must be completely separate from the test logic itself.
2. **Non-interference**: Tracing must not affect the execution or results of tests.
3. **Observability Only**: The tracing should be purely observational, with no impact on client behavior.
4. **Consistent Output**: All trace data must be captured in the Hive log file, which is the only artifact that persists after test runs.
5. **Optional Activation**: Tracing should be controlled via environment variables, allowing it to be enabled or disabled without modifying code.

### Architecture Overview

The general architecture for instruction-level tracing consists of:

```
┌────────────────────────────────────────────────────────────────┐
│                      Hive Testing Framework                     │
│                                                                │
│  ┌─────────────────────────────────────────────────────────┐  │
│  │                       Docker Container                  │  │
│  │                                                         │  │
│  │   ┌───────────────┐          ┌───────────────────┐     │  │
│  │   │ Client Binary │◄─────────┤ Debugging Tool    │     │  │
│  │   │ (with debug   │          │ (GDB/LLDB/etc.)   │     │  │
│  │   │  symbols)     │          └───────┬───────────┘     │  │
│  │   └───────────────┘                  │                 │  │
│  │                                      │                 │  │
│  │                                      ▼                 │  │
│  │                           ┌───────────────────┐       │  │
│  │                           │ Tracing Script    │       │  │
│  │                           └─────────┬─────────┘       │  │
│  │                                     │                 │  │
│  └─────────────────────────────────────┼─────────────────┘  │
│                                        │                    │
│                                        ▼                    │
│                               HIVE_TRACE output             │
│                              (captured in logs)             │
└────────────────────────────────────────────────────────────────┘
```

### Implementation Requirements

To implement instruction-level tracing, you'll need:

1. **Debug-enabled Client**: The client must be built with debug symbols.
2. **Appropriate Debugging Tool**: A tool suitable for the client's implementation language:
   - C/C++/Rust: GDB or LLDB
   - Go: Delve
   - JavaScript: V8 Inspector
   - JVM languages: JDB or custom JVM debugging tools

3. **Tracing Script**: A script that interfaces with the debugging tool to:
   - Attach to the running client process
   - Step through instructions
   - Extract source location information
   - Output formatted trace data

4. **Modified Entry Point**: A modified entry-point script that conditionally runs the client through the debugger when an environment variable is set.

### Workflow

The general workflow is:

1. Build the client with debug symbols enabled
2. Set up the debugger and tracing script in the Docker image
3. Modify the client's entry point to check for the tracing environment variable
4. Run the client through the debugger when tracing is enabled
5. Capture all trace output with a specific prefix in the Hive logs

### Debugging Tools

Common debugging tools by language:

| Language | Debugging Tool | Notes |
|----------|----------------|-------|
| C/C++ | GDB | GNU Debugger, widely available |
| Rust | GDB/LLDB | Both can debug Rust code with debug symbols |
| Go | Delve | Native Go debugger |
| JavaScript | V8 Inspector | For Node.js applications |
| Java | JDB | Java Debugger |
| Python | PDB | Python Debugger |

---

## Reth Implementation Example

This section demonstrates a specific implementation of instruction-level tracing for the reth client, which is written in Rust.

### Files Overview

Three main files are involved in the implementation:

1. `Dockerfile`: Modified to build reth with debug symbols and include debugging tools
2. `reth.sh`: The client's entry point script, modified to conditionally use GDB
3. `trace_instructions.py`: A GDB Python script to handle the actual tracing

### Dockerfile Changes

```dockerfile
# First stage: Build reth with debug symbols
FROM rust:slim as builder

# Install build dependencies
RUN apt-get update -y && apt-get install -y bash curl git pkg-config libssl-dev jq clang libclang-dev make

# Clone reth source code
WORKDIR /src
RUN git clone https://github.com/paradigmxyz/reth.git .

# Copy scripts and configs
COPY genesis.json /genesis.json
COPY mapper.jq /mapper.jq
COPY reth.sh /reth.sh
RUN chmod +x /reth.sh
COPY enode.sh /hive-bin/enode.sh
RUN chmod +x /hive-bin/enode.sh

# Build reth with debug symbols 
RUN RUSTFLAGS="-g" cargo build --bin reth

# Copy binary to /usr/local/bin for compatibility with scripts
RUN cp /src/target/debug/reth /usr/local/bin/reth

# Create version.txt
RUN /usr/local/bin/reth --version | sed -e 's/reth \(.*\)/\1/' > /version.txt

# Second stage: Runtime environment with debugging tools
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

# Copy GDB Python tracing script
COPY trace_instructions.py /trace_instructions.py

# Set environment variable for tracing (can be overridden at runtime)
ENV HIVE_TRACE_INSTRUCTIONS=1

# Export the usual networking ports
EXPOSE 8545 8546 30303 30303/udp

ENTRYPOINT ["/reth.sh"]
```

Key changes in the Dockerfile:

1. Using a multi-stage build for efficiency
2. Building reth with debug symbols (using `RUSTFLAGS="-g"`)
3. Including GDB and Python in the runtime environment
4. Copying the tracing script to the container
5. Setting the environment variable to enable tracing by default

### Client Shell Script

The `reth.sh` script is modified to conditionally run the client through GDB when tracing is enabled:

```bash
# Launch the main client.
echo "Running reth with flags: $FLAGS"

# Debug environment variable
echo "HIVE_TRACE_INSTRUCTIONS value: [${HIVE_TRACE_INSTRUCTIONS}]"

# Enable conditional GDB tracing
if [ "${HIVE_TRACE_INSTRUCTIONS}" = "1" ]; then
    echo "HIVE_TRACE: Instruction tracing enabled - running reth through GDB"
    # Run with GDB and our tracing script
    gdb -q -x /trace_instructions.py --args $reth node $FLAGS
else
    # Normal execution without tracing
    RUST_LOG=info $reth node $FLAGS
fi
```

Key aspects:
1. Checking for the `HIVE_TRACE_INSTRUCTIONS` environment variable
2. Running reth through GDB with the tracing script when enabled
3. Running reth normally when tracing is disabled

### GDB Tracing Script

The `trace_instructions.py` script handles the actual tracing:

```python
import gdb
import sys
import os
import time

# Set up logging to ensure all output is captured by Hive
def trace_log(message):
    print(f"HIVE_TRACE: {message}", flush=True)

# Handle instruction tracing, which will log source location information when available
class TraceInstructions:
    def __init__(self):
        self.last_file = None
        self.last_line = None
        self.instructions_count = 0
        self.start_time = time.time()
        
    def trace(self):
        try:
            # Try to get current frame information
            frame = gdb.selected_frame()
            if frame is None:
                return
                
            sal = frame.find_sal()
            
            # Only log when hitting a new source line to reduce volume
            if sal.symtab and (sal.symtab.filename != self.last_file or sal.line != self.last_line):
                self.last_file = sal.symtab.filename
                self.last_line = sal.line
                trace_log(f"SRC: {sal.symtab.filename}:{sal.line}")
                
            self.instructions_count += 1
            
            # Print statistics every 10000 instructions
            if self.instructions_count % 10000 == 0:
                elapsed = time.time() - self.start_time
                if elapsed > 0:
                    trace_log(f"STATS: Executed {self.instructions_count} instructions in {elapsed:.2f} seconds ({self.instructions_count/elapsed:.2f} instr/sec)")
                    
        except Exception as e:
            # Silently handle errors - just continue tracing
            pass

# Main tracing function
def start_tracing():
    trace_log("Starting GDB tracing for reth")
    
    # Set up GDB
    gdb.execute("set pagination off")
    gdb.execute("set confirm off")
    
    # Log GDB and python versions
    trace_log(f"GDB version: {gdb.VERSION}")
    trace_log(f"Python version: {sys.version}")
    
    # Prepare for tracing
    tracer = TraceInstructions()
    
    try:
        # Run to main - start the program
        trace_log("Starting program...")
        gdb.execute("start", to_string=True)
        trace_log("Program started, beginning instruction tracing")
        
        # Use a soft loop count to avoid hanging indefinitely
        max_instructions = 10000000  # Cap at 10M instructions for safety
        
        # Trace instructions
        for i in range(max_instructions):
            if i % 10000 == 0:
                trace_log(f"Traced {i} instructions")
                
            # Perform tracing on this instruction
            tracer.trace()
            
            # Execute one instruction
            try:
                gdb.execute("stepi", to_string=True)
            except gdb.error:
                trace_log("Program finished execution or hit an error")
                break
                
    except KeyboardInterrupt:
        trace_log("Tracing stopped by user (CTRL+C)")
    except gdb.error as e:
        trace_log(f"GDB error: {e}")
    except Exception as e:
        trace_log(f"Unexpected error: {str(e)}")
    finally:
        # Clean up
        try:
            trace_log("Ending trace session, terminating program")
            gdb.execute("kill", to_string=True)
            trace_log(f"Total instructions traced: {tracer.instructions_count}")
        except:
            pass

# Start tracing when this script is executed
trace_log("GDB script initialized")
start_tracing()
```

Key features:
1. Using the GDB Python API to control the debugging session
2. Tracing instructions and extracting source location
3. Handling missing debug symbols gracefully
4. Collecting and reporting execution statistics
5. Prefixing all output with "HIVE_TRACE:" for easy filtering
6. Safety mechanisms to prevent infinite loops

### Usage

To run Hive tests with the instruction tracing enabled:

```bash
# Tracing enabled (default in this implementation)
./hive --sim ethereum/eest/consume-rlp --client reth [other options]

# Explicitly enable tracing
HIVE_TRACE_INSTRUCTIONS=1 ./hive --sim ethereum/eest/consume-rlp --client reth [other options]

# Disable tracing
HIVE_TRACE_INSTRUCTIONS=0 ./hive --sim ethereum/eest/consume-rlp --client reth [other options]
```

### Output Format

The trace output in the Hive logs will look like:

```
HIVE_TRACE: GDB script initialized
HIVE_TRACE: Starting GDB tracing for reth
HIVE_TRACE: GDB version: 13.1
HIVE_TRACE: Python version: 3.11.2 (main, Nov 30 2024, 21:22:50) [GCC 12.2.0]
HIVE_TRACE: Starting program...
HIVE_TRACE: Program started, beginning instruction tracing
HIVE_TRACE: Traced 0 instructions
HIVE_TRACE: SRC: /rustc/05f9846f893b09a1be1fc8560e33fc3c815cfecb/library/std/src/rt.rs:192
HIVE_TRACE: SRC: /rustc/05f9846f893b09a1be1fc8560e33fc3c815cfecb/library/std/src/rt.rs:199
HIVE_TRACE: SRC: /rustc/05f9846f893b09a1be1fc8560e33fc3c815cfecb/library/std/src/rt.rs:198
HIVE_TRACE: SRC: library/std/src/rt.rs:145
HIVE_TRACE: STATS: Executed 10000 instructions in 2.34 seconds (4273.50 instr/sec)
```

---

## Extending to Other Clients

The approach described for reth can be adapted to other Ethereum clients by:

1. Building the client with debug symbols
2. Including the appropriate debugging tool for the client's language
3. Creating a tracing script specific to that debugger
4. Modifying the client's entry point to use the debugger when tracing is enabled

### Examples for Different Languages

#### Go Clients (like go-ethereum)

For Go-based clients, the [Delve](https://github.com/go-delve/delve) debugger would be used instead of GDB, with a custom script interfacing with Delve's API.

#### JavaScript Clients (like ethereumjs)

For JavaScript clients, V8's debugging capabilities could be used, potentially with Chrome DevTools Protocol or Node.js's built-in inspector.

#### JVM-based Clients (like Hyperledger Besu in Java)

For Java clients, JDB or a custom JVM tool using the Java Debug Interface (JDI) would be appropriate.

---

The key to successful implementation across clients is maintaining the core principles while adapting the specific tools and scripts to each client's programming language and infrastructure.
