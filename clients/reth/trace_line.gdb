# ensure GDB loads the correct object file
file /reth-source/target/debug/reth

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

# Set breakpoints
#rbreak ^tokio.*::

#commands
#  silent             
#  info line *$pc
#  continue           
#end

run

set $i = 0
while $i < 1000
  next
  info line *$pc
  set $i = $i + 1
end