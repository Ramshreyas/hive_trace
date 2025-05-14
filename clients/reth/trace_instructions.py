import gdb
import sys
import os
import time

# Set up logging to ensure all output is captured by Hive
def trace_log(message):
    print(f"HIVE_TRACE: {message}", flush=True)

# Handle instruction tracing, which will log source location information when available
class TraceInstructions:
    def __init__(self):
        self.last_file = None
        self.last_line = None
        self.instructions_count = 0
        self.start_time = time.time()
        
    def trace(self):
        try:
            # Try to get current frame information
            frame = gdb.selected_frame()
            if frame is None:
                return
                
            sal = frame.find_sal()
            
            # Only log when hitting a new source line to reduce volume
            if sal.symtab and (sal.symtab.filename != self.last_file or sal.line != self.last_line):
                self.last_file = sal.symtab.filename
                self.last_line = sal.line
                trace_log(f"SRC: {sal.symtab.filename}:{sal.line}")
                
            self.instructions_count += 1
            
            # Print statistics every 10000 instructions
            if self.instructions_count % 10000 == 0:
                elapsed = time.time() - self.start_time
                if elapsed > 0:
                    trace_log(f"STATS: Executed {self.instructions_count} instructions in {elapsed:.2f} seconds ({self.instructions_count/elapsed:.2f} instr/sec)")
                    
        except Exception as e:
            # Silently handle errors - just continue tracing
            pass

# Main tracing function
def start_tracing():
    trace_log("Starting GDB tracing for reth")
    
    # Set up GDB
    gdb.execute("set pagination off")
    gdb.execute("set confirm off")
    
    # Log GDB and python versions
    trace_log(f"GDB version: {gdb.VERSION}")
    trace_log(f"Python version: {sys.version}")
    
    # Prepare for tracing
    tracer = TraceInstructions()
    
    try:
        # Run to main - start the program
        trace_log("Starting program...")
        gdb.execute("start", to_string=True)
        trace_log("Program started, beginning instruction tracing")
        
        # Use a soft loop count to avoid hanging indefinitely
        max_instructions = 10000000  # Cap at 10M instructions for safety
        
        # Trace instructions
        for i in range(max_instructions):
            if i % 10000 == 0:
                trace_log(f"Traced {i} instructions")
                
            # Perform tracing on this instruction
            tracer.trace()
            
            # Execute one instruction
            try:
                gdb.execute("stepi", to_string=True)
            except gdb.error:
                trace_log("Program finished execution or hit an error")
                break
                
    except KeyboardInterrupt:
        trace_log("Tracing stopped by user (CTRL+C)")
    except gdb.error as e:
        trace_log(f"GDB error: {e}")
    except Exception as e:
        trace_log(f"Unexpected error: {str(e)}")
    finally:
        # Clean up
        try:
            trace_log("Ending trace session, terminating program")
            gdb.execute("kill", to_string=True)
            trace_log(f"Total instructions traced: {tracer.instructions_count}")
        except:
            pass

# Start tracing when this script is executed
trace_log("GDB script initialized")
start_tracing()
