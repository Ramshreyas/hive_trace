# Tidy up GDB output
set pagination off
set confirm off

# If the test harness itself writes to a closed pipe, ignore SIGPIPE
handle SIGPIPE nostop noprint pass

# Allow breakpoints on symbols not yet loaded
set breakpoint pending on
set follow-fork-mode child

# Break on every reth function
rbreak ^reth.*::

run

# Loop: step one source line, then print its .rs:line (if any)
while 1
  next
  printf "TRACE:"
  info line *$pc
end
