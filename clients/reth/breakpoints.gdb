# breakpoints.gdb

# set a breakpoint at line 122, with its own commands block
break crates/cli/util/src/sigsegv_handler.rs:122
commands
  silent
  info line *$pc
  continue
end

# breakpoint at line 140
break crates/cli/util/src/sigsegv_handler.rs:140
commands
  silent
  info line *$pc
  continue
end

# breakpoint at line 144
break crates/cli/util/src/sigsegv_handler.rs:144
commands
  silent
  info line *$pc
  continue
end
