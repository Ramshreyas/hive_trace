# hive - Ethereum end-to-end test harness (Tracing Fork)

This repository is a **fork** of the Ethereum Foundation's Hive testing harness, customized to enable **execution tracing of Ethereum clients** as they are run against EIP tests.

## What’s Different in This Fork?

This fork adds the ability to **trace execution clients** during EIP test runs, providing insight into which lines of code are executed for a given test. This is achieved through the following customizations:

1. **Dockerfile Modifications**  
   The Dockerfile is modified to build execution clients from source, enabling debugging and instrumentation.

2. **Dynamic Breakpoint Generation**  
   Breakpoints are dynamically generated based on a specified objective (e.g., tracing code paths relevant to a particular EIP or function).

3. **Automated Debugging**  
   The program is run inside GDB (or a similar debugger) within the test harness, allowing for automated tracing and collection of execution data.

4. **Filtered Output**  
   After the test run, the output is filtered to show only the lines of code (LoC) that were executed for the given test, making it easy to analyze code coverage and behavior.

## How to Run

To run a traced test, use the provided script:

```sh
./test_trace.sh --client <client> --test <test_case> --output <output file>
```

- `<client>`: The execution client to trace (e.g., geth, nethermind)
- `<test_case>`: The EIP test or scenario to run
- `<output file>`: The output file

The script will:
- Build the client from source with debug symbols
- Set up dynamic breakpoints according to the objective
- Run the client under GDB during the test
- Output the filtered list of executed lines for analysis

---

🚧 **Work in progress: This fork is under active development. Features and documentation may change.** 🚧

