# Tidy up GDB output
set pagination off
set confirm off

# If the test harness itself writes to a closed pipe, ignore SIGPIPE
handle SIGPIPE nostop noprint pass

# Allow breakpoints on symbols not yet loaded
set breakpoint pending on
set follow-fork-mode child

# Demangle Rust symbols in GDB output
set print demangle on

# === Define a global hook that runs on every breakpoint stop ===
define hook-stop
  # $bpnum is nonzero if this stop was due to a breakpoint
  if $bpnum
    info line *$pc
    continue
  end
end

# Now set your regex breakpoints (even if it makes dozens or thousands)
rbreak '^block_on<.*reth_.*::'

info breakpoints

# Launch your program
run
