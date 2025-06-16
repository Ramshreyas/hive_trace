# ensure GDB loads the correct object file
file /usr/local/bin/geth

# Tidy up GDB output
set pagination off
set confirm off

# If the test harness itself writes to a closed pipe, ignore SIGPIPE
handle SIGPIPE nostop noprint pass

# Allow breakpoints on symbols not yet loaded
set breakpoint pending on

# Follow threads
set follow-fork-mode child

# Set breakpoints
source /eip_breakpoints.gdb

run