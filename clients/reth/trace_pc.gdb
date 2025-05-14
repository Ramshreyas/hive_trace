set pagination off
set confirm off
start
define hook-stop
  printf "HIVE_TRACE: %p\n", $pc
end
while 1
  stepi
end
