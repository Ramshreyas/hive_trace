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

# only break on your real, hyphen→underscore crates
rbreak ^reth_.*::

info breakpoints

#commands
#  silent             
#  info line *$pc
#  continue           
#end

run
