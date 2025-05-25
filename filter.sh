#!/bin/bash
# filepath: filter_traces.sh

if [[ $# -ne 2 ]]; then
    echo "Usage: $0 <input_log_file> <output_file>"
    exit 1
fi

INPUT="$1"
OUTPUT="$2"

awk '
    function print_block() {
        if (trace_count > 0 && test_name != "unknown") {
            print "TEST: " test_name " STATUS: " test_status
            for (i=1; i<=trace_count; i++) print trace[i]
            print "---"
        }
    }
    # Match pytest result lines
    /^\[[0-9a-f]+\] .* (PASSED|FAILED|SKIPPED) \[[ 0-9\/]+\]$/ {
        print_block()
        # Extract test name and status using regex
        # Example: [08f3b6a4] path::to::test PASSED [  1/490]
        line = $0
        sub(/^\[[0-9a-f]+\] /, "", line)      # Remove hash prefix
        sub(/ (PASSED|FAILED|SKIPPED) \[[ 0-9\/]+\]$/, "", line) # Remove status and count
        test_name = line
        if ($0 ~ / PASSED /) test_status = "PASSED"
        else if ($0 ~ / FAILED /) test_status = "FAILED"
        else if ($0 ~ / SKIPPED /) test_status = "SKIPPED"
        else test_status = "UNKNOWN"
        in_test = 1
        trace_count = 0
        next
    }
    # Match API result lines
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

echo "Trace filtering complete. Output written to $OUTPUT"