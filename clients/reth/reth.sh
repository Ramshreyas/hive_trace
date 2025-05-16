#!/bin/bash

# Immediately abort the script on any error encountered
set -ex

# no ansi colors
export RUST_LOG_STYLE=never

reth=/reth-source/target/debug/reth

case "$HIVE_LOGLEVEL" in
    0|1) FLAGS="$FLAGS -v" ;;
    2)   FLAGS="$FLAGS -vv" ;;
    3)   FLAGS="$FLAGS -vvv" ;;
    4)   FLAGS="$FLAGS -vvvv" ;;
    5)   FLAGS="$FLAGS -vvvvv" ;;
esac

# Create the data directory.
DATADIR="/reth-hive-datadir"
mkdir $DATADIR
FLAGS="$FLAGS --datadir $DATADIR"

# Configure the chain.
mv /genesis.json /genesis-input.json
jq -f /mapper.jq /genesis-input.json > /genesis.json

# Dump genesis.
if [ "$HIVE_LOGLEVEL" -lt 4 ]; then
    echo "Supplied genesis state (trimmed, use --sim.loglevel 4 or 5 for full output):"
    jq 'del(.alloc[] | select(.balance == "0x123450000000000000000"))' /genesis.json
else
    echo "Supplied genesis state:"
    cat /genesis.json
fi

echo "Command flags till now:"
echo $FLAGS

# Initialize the local testchain with the genesis state
echo "Initializing database with genesis state..."
$reth init $FLAGS --chain /genesis.json

# Make sure pruner doesn't start
echo -e "[prune]\\nblock_interval = 500_000" >> $DATADIR/reth.toml

# make sure we use the same genesis each time
FLAGS="$FLAGS --chain /genesis.json"

# Don't immediately abort, some imports are meant to fail
set +ex

# Load the test chain if present
echo "Loading initial blockchain..."
if [ -f /chain.rlp ]; then
    RUST_LOG=info $reth import $FLAGS /chain.rlp
else
    echo "Warning: chain.rlp not found."
fi

# Load the remainder of the test chain
echo "Loading remaining individual blocks..."
mapfile -t BLOCKS < <(ls /blocks/*.rlp 2>/dev/null | sort -n)

if [[ ! -d "/blocks" || ${#BLOCKS[@]} -eq 0 ]]; then
    echo "Warning: No blocks found."
elif [[ ${#BLOCKS[@]} -eq 1 ]]; then
    # Import the only existing block
    $reth import $FLAGS "${BLOCKS[0]}"
else
    # First import as many blocks as possible, and only then import the last one.
    # This is important because usually tests expecting a failure will assert that the last valid inserted block is at last - 1. If we attempted to import all of them the pipeline would unwind the whole range.
    cat "${BLOCKS[@]:0:${#BLOCKS[@]}-1}" > "combined.rlp"

    # Import all but the last block first
    $reth import $FLAGS "combined.rlp"

    # Import the last block separately
    $reth import $FLAGS "${BLOCKS[-1]}"
fi

# Only set boot nodes in online steps
# It doesn't make sense to dial out, use only a pre-set bootnode.
if [ "$HIVE_BOOTNODE" != "" ]; then
    FLAGS="$FLAGS --bootnodes=$HIVE_BOOTNODE"
fi

# If clique is expected enable auto-mine
if [ -n "${HIVE_CLIQUE_PRIVATEKEY}" ] || [ -n "${HIVE_CLIQUE_PERIOD}" ]; then
  FLAGS="$FLAGS --auto-mine"
  if [ -n "${HIVE_CLIQUE_PERIOD}" ]; then
    FLAGS="$FLAGS --dev.block-time ${HIVE_CLIQUE_PERIOD}s"
  fi
fi

# Configure RPC.
FLAGS="$FLAGS --http --http.addr=0.0.0.0 --http.api=admin,debug,eth,net,web3"
FLAGS="$FLAGS --ws --ws.addr=0.0.0.0 --ws.api=admin,debug,eth,net,web3"

if [ "$HIVE_TERMINAL_TOTAL_DIFFICULTY" != "" ]; then
    JWT_SECRET="7365637265747365637265747365637265747365637265747365637265747365"
    echo -n $JWT_SECRET > /jwt.secret
    FLAGS="$FLAGS --authrpc.addr=0.0.0.0 --authrpc.jwtsecret=/jwt.secret"
fi

# Configure NAT
FLAGS="$FLAGS --nat none"

# Launch the main client.
echo "Running reth with flags: $FLAGS"

# Change to source directory where the debug build resides
cd /reth-source

# Generate the breakpoints
python3 /generate_breakpoints.py --crates-root /reth-source reth-cli-util

# Run with tracing
echo "TRACE: Line-level tracing enabled - running reth through GDB (trace_line.gdb)"
# Run with GDB and the line-level tracing script
gdb -q -x /trace_line.gdb --args $reth node $FLAGS
