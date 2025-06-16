#!/bin/bash
# filepath: /home/ramshreyas/Documents/Dev/ETHFoundation/hive/test_trace.sh

set -e

usage() {
    echo "Usage: $0 --client <go-ethereum|reth> --test <test> --output <output_file>"
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
        *)
            usage
            ;;
    esac
done

if [[ -z "$CLIENT" || -z "$TEST" || -z "$OUTPUT" ]]; then
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

# Run the hive command
./hive --sim ethereum/eest/consume-rlp \
    --client $CLIENT \
    --sim.buildarg fixtures=develop@latest \
    --sim.limit "$TEST" \
    --docker.nocache "$CLIENT" \
    --client.checktimelimit 1200m \
    --sim.timelimit 1200m \
    --docker.output > "$OUTPUT" 2>&1

echo "Trace complete. Output written to $OUTPUT"

# --- Begin filter logic ---
FILTERED="${OUTPUT}.filtered"

# Count number of test result lines (avoid double-counting)
NUM_TESTS=$(grep -E '^\[[0-9a-f]+\] .* (PASSED|FAILED|SKIPPED) \[[ 0-9/]+\]$' "$OUTPUT" | wc -l)
if [[ "$NUM_TESTS" -eq 0 ]]; then
    NUM_TESTS=$(grep -E 'API: test ended' "$OUTPUT" | wc -l)
fi
echo "Detected $NUM_TESTS test(s) in $OUTPUT"

if [[ "$NUM_TESTS" -eq 1 ]]; then
    # Prefer pytest result line for test name/status
    TEST_LINE=$(grep -m1 -E '^\[[0-9a-f]+\] .* (PASSED|FAILED|SKIPPED) \[[ 0-9/]+\]$' "$OUTPUT")
    if [[ -n "$TEST_LINE" ]]; then
        TEST_NAME=$(echo "$TEST_LINE" | sed -E 's/^\[[0-9a-f]+\] (.*) (PASSED|FAILED|SKIPPED) \[[ 0-9/]+\]$/\1/')
        TEST_STATUS=$(echo "$TEST_LINE" | sed -nE 's/.* (PASSED|FAILED|SKIPPED) \[[ 0-9/]+\]$/\1/p')
    else
        TEST_LINE=$(grep -m1 'API: test ended' "$OUTPUT")
        TEST_NAME=$(echo "$TEST_LINE" | sed -n 's/.*test=\([0-9]\+\).*/test_\1/p')
        [[ "$TEST_LINE" =~ pass=([a-z]+) ]] && [[ "${BASH_REMATCH[1]}" == "true" ]] && TEST_STATUS="PASSED" || TEST_STATUS="FAILED"
    fi
    {
        echo "TEST: $TEST_NAME STATUS: $TEST_STATUS"
        grep ' Line ' "$OUTPUT"
        echo "---"
    } > "$FILTERED"
else
    awk '
        BEGIN {
            prev_test_name = ""
            prev_test_status = ""
            trace_count = 0
            seen_result = 0
        }
        # Collect all trace lines
        / Line / {
            trace[++trace_count] = $0
            next
        }
        # When a test result line is seen, print the previous block of traces
        /^\[[0-9a-f]+\] .* (PASSED|FAILED|SKIPPED) \[[ 0-9\/]+\]$/ {
            if (seen_result && prev_test_name != "") {
                print "TEST: " prev_test_name " STATUS: " prev_test_status
                for (i=1; i<=trace_count; i++) print trace[i]
                print "---"
            }
            # Extract test name and status for the *next* block
            line = $0
            sub(/^\[[0-9a-f]+\] /, "", line)
            sub(/ (PASSED|FAILED|SKIPPED) \[[ 0-9\/]+\]$/, "", line)
            prev_test_name = line
            if ($0 ~ / PASSED /) prev_test_status = "PASSED"
            else if ($0 ~ / FAILED /) prev_test_status = "FAILED"
            else if ($0 ~ / SKIPPED /) prev_test_status = "SKIPPED"
            else prev_test_status = "UNKNOWN"
            trace_count = 0
            seen_result = 1
            next
        }
        # API test ended lines (optional, similar logic)
        /API: test ended/ {
            if (seen_result && prev_test_name != "") {
                print "TEST: " prev_test_name " STATUS: " prev_test_status
                for (i=1; i<=trace_count; i++) print trace[i]
                print "---"
            }
            prev_test_name = "unknown"
            prev_test_status = "UNKNOWN"
            if ($0 ~ /test=[0-9]+/) {
                split($0, a, "test=")
                split(a[2], b, " ")
                prev_test_name = "test_" b[1]
            }
            if ($0 ~ /pass=[a-z]+/) {
                split($0, c, "pass=")
                split(c[2], d, " ")
                prev_test_status = (d[1] == "true" ? "PASSED" : "FAILED")
            }
            trace_count = 0
            seen_result = 1
            next
        }
        END {
            if (seen_result && prev_test_name != "") {
                print "TEST: " prev_test_name " STATUS: " prev_test_status
                for (i=1; i<=trace_count; i++) print trace[i]
                print "---"
            }
        }
    ' "$OUTPUT" > "$FILTERED"
fi

echo "Trace filtering complete. Output written to $FILTERED"
# --- End filter logic ---