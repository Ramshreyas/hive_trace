# ensure GDB loads the correct object file
file /reth-source/target/debug/reth

# Tidy up GDB output
set pagination off
set confirm off

# If the test harness itself writes to a closed pipe, ignore SIGPIPE
handle SIGPIPE nostop noprint pass

# Allow breakpoints on symbols not yet loaded
set breakpoint pending on

# Follow threads
set follow-fork-mode child

# Demangle Rust symbols in GDB output
set print demangle on

# Set breakpoints
source breakpoints.gdb

run