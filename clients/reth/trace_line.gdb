# trace_line.gdb - GDB script for address-only tracing (DWARF address)

set pagination off
set confirm off
# set breakpoint pending on
set follow-fork-mode child
break main
run

define hook-stop
  printf "HIVE_TRACE: 0x%lx ", $pc
  info line *$pc
end

start
while 1
  step
end

