set pagination off
set confirm off
set follow-fork-mode child

break main
run

set scheduler-locking off

define hook-stop
  printf "EX_TRACE: "
  info line *$pc
end

start

set $i = 0
while $i < 10000000
  step
  set $i = $i + 1
end
