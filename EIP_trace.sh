#!/bin/bash
# filepath: /home/ramshreyas/Documents/Dev/ETHFoundation/hive/EIP_trace.sh

set -e

usage() {
    echo "Usage: $0 --client <go-ethereum|reth> --test <test> --output <output_file> --targets <targets_file>"
    exit 1
}

# Parse arguments
while [[ $# -gt 0 ]]; do
    case "$1" in
        --client)
            CLIENT="$2"
            shift 2
            ;;
        --test)
            TEST="$2"
            shift 2
            ;;
        --output)
            OUTPUT="$2"
            shift 2
            ;;
        --targets)
            TARGETS="$2"
            shift 2
            ;;
        *)
            usage
            ;;
    esac
done

if [[ -z "$CLIENT" || -z "$TEST" || -z "$OUTPUT" || -z "$TARGETS" ]]; then
    usage
fi

if [[ "$CLIENT" == "go-ethereum" ]]; then
    TARGET_DIR="clients/go-ethereum"
elif [[ "$CLIENT" == "reth" ]]; then
    TARGET_DIR="clients/reth"
else
    echo "Invalid client: $CLIENT"
    usage
fi

# Copy the specified targets file to the client directory
if [[ ! -f "$TARGETS" ]]; then
    echo "$TARGETS not found."
    exit 1
fi

cp "$TARGETS" "$TARGET_DIR/targets.txt"

# Run the hive command
./hive --sim ethereum/eest/consume-rlp \
    --client $CLIENT \
    --sim.buildarg fixtures=develop@latest \
    --sim.limit "$TEST" \
    --docker.nocache "$CLIENT" \
    --client.checktimelimit 1200m \
    --sim.timelimit 1200m \
    --docker.output > "$OUTPUT" 2>&1

# Filter the output file to only include lines containing ' Line '
grep ' Line ' "$OUTPUT" > "${OUTPUT}.filtered"
mv "${OUTPUT}.filtered" "$OUTPUT"

echo "Trace complete. Output written to $OUTPUT"