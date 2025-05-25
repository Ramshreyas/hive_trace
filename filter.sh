#!/bin/bash
# filepath: filter_traces.sh

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <input_log_file> <output_file>"
    exit 1
fi

INPUT="$1"
OUTPUT="$2"

# Count number of test result lines
NUM_TESTS=$(grep -E '^\[[0-9a-f]+\] .* (PASSED|FAILED|SKIPPED) \[[ 0-9/]+\]$' "$INPUT" | wc -l)
echo "Detected $NUM_TESTS test(s) in $INPUT"

if [[ "$NUM_TESTS" -eq 1 ]]; then
    # Prefer pytest result line for test name/status
    TEST_LINE=$(grep -m1 -E '^\[[0-9a-f]+\] .* (PASSED|FAILED|SKIPPED) \[[ 0-9/]+\]$' "$INPUT")
    if [[ -n "$TEST_LINE" ]]; then
        # Extract test name and status from pytest line
        TEST_NAME=$(echo "$TEST_LINE" | sed -E 's/^\[[0-9a-f]+\] (.*) (PASSED|FAILED|SKIPPED) \[[ 0-9/]+\]$/\1/')
        TEST_STATUS=$(echo "$TEST_LINE" | sed -nE 's/.* (PASSED|FAILED|SKIPPED) \[[ 0-9/]+\]$/\1/p')
    else
        # Fallback to API line
        TEST_LINE=$(grep -m1 'API: test ended' "$INPUT")
        TEST_NAME=$(echo "$TEST_LINE" | sed -n 's/.*test=\([0-9]\+\).*/test_\1/p')
        [[ "$TEST_LINE" =~ pass=([a-z]+) ]] && [[ "${BASH_REMATCH[1]}" == "true" ]] && TEST_STATUS="PASSED" || TEST_STATUS="FAILED"
    fi
    {
        echo "TEST: $TEST_NAME STATUS: $TEST_STATUS"
        grep ' Line ' "$INPUT"
        echo "---"
    } > "$OUTPUT"
else
    # Multi-test case: use original awk logic
    awk '
        function print_block() {
            if (trace_count > 0 && test_name != "unknown") {
                print "TEST: " test_name " STATUS: " test_status
                for (i=1; i<=trace_count; i++) print trace[i]
                print "---"
            }
        }
        /^\[[0-9a-f]+\] .* (PASSED|FAILED|SKIPPED) \[[ 0-9\/]+\]$/ {
            print_block()
            line = $0
            sub(/^\[[0-9a-f]+\] /, "", line)
            sub(/ (PASSED|FAILED|SKIPPED) \[[ 0-9\/]+\]$/, "", line)
            test_name = line
            if ($0 ~ / PASSED /) test_status = "PASSED"
            else if ($0 ~ / FAILED /) test_status = "FAILED"
            else if ($0 ~ / SKIPPED /) test_status = "SKIPPED"
            else test_status = "UNKNOWN"
            in_test = 1
            trace_count = 0
            next
        }
        /API: test ended/ {
            print_block()
            test_name = "unknown"
            test_status = "UNKNOWN"
            if ($0 ~ /test=[0-9]+/) {
                split($0, a, "test=")
                split(a[2], b, " ")
                test_name = "test_" b[1]
            }
            if ($0 ~ /pass=[a-z]+/) {
                split($0, c, "pass=")
                split(c[2], d, " ")
                test_status = (d[1] == "true" ? "PASSED" : "FAILED")
            }
            in_test = 1
            trace_count = 0
            next
        }
        / Line / && in_test {
            trace[++trace_count] = $0
            next
        }
        END {
            print_block()
        }
    ' "$INPUT" > "$OUTPUT"
fi

echo "Trace filtering complete. Output written to $OUTPUT"