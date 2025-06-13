#!/usr/bin/env python3
"""
annotate_modules.py — Phase 4-M1
Generate 1-sentence summaries for each module based on README/docs in module directories.
"""

import os, json, pathlib, textwrap
from google import genai
from google.genai.types import GenerateContentConfig

SUBS = pathlib.Path("/output/module_subgraphs.json")
OUT  = pathlib.Path("/output/module_summaries.json")
DRY  = os.getenv("USE_LLM", "0") != "1"

module_data = json.loads(SUBS.read_text())
summaries = {}

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY")) if not DRY else None

for mod in module_data.keys():
    p = pathlib.Path(mod)
    if p.exists():
        read = ""
        for name in ("README.md", "README", "doc.go"):
            r = p / name
            if r.exists():
                read = "\n".join(r.read_text().splitlines()[:15])
                break
    else:
        read = ""

    prompt = textwrap.dedent(f"""
Directory path: {mod}

Context:
{read}

In one sentence, describe the primary purpose of this module (a module is a single directory boundary).
""").strip()

    if DRY:
        summaries[mod] = "(TODO module summary)"
    else:
        res = client.models.generate_content(
            model="gemini-2.5-flash-preview-05-20",
            contents=prompt,
                config=GenerateContentConfig(
                temperature=0.2,
                top_p=0.95,
                top_k=20,
                max_output_tokens=4096,
            ),
        )
        summaries[mod] = res.text.strip()
        print(f"✅ {mod} summarized")

OUT.write_text(json.dumps(summaries, indent=2))
print("✅ module_summaries.json written")
