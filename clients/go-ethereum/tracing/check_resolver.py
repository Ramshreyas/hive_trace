from resolve_function_from_id import load_meta, snippet

# your JSON lives in ./output/functions.json
load_meta("output/functions.json")       

fp, code = snippet("(*Config).ExtRPCEnabled", ctx=2)
print(fp)
print(code)
