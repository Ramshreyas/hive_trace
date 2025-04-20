# trace_line.gdb - GDB script for address-only tracing (DWARF address)

set pagination off
set confirm off
set breakpoint pending on

define hook-stop
  printf "HIVE_TRACE: 0x%lx ", $pc
  info line *$pc
end

start
while 1
  step
end

# Optionally, set a catchpoint for signals (optional)
# catch signal SIGSEGV
