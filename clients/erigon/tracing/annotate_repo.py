#!/usr/bin/env python3
import os, pathlib, textwrap
from google import genai
from google.genai.types import GenerateContentConfig

ROOT        = pathlib.Path("/build")
OUT_FILE    = pathlib.Path("/output/repo_summary.txt")
DRY_RUN     = os.getenv("USE_LLM", "0") != "1"
API_KEY     = os.getenv("GEMINI_API_KEY")

# Read the project README
for name in ("README.md","README","README.txt"):
    p = ROOT/name
    if p.exists():
        readme = p.read_text()
        break
else:
    raise RuntimeError("README not found")

prompt = textwrap.dedent(f"""
Below is the project README. Please summarise the purpose of the repository in two concise sentences.

README:
{readme[:6000]}
""").strip()

if DRY_RUN:
    OUT_FILE.write_text("(TODO repo summary)")
    print("🔹 Dry-run: placeholder written.")
else:
    # Initialize the Gemini client
    client = genai.Client(api_key=API_KEY)

    response = client.models.generate_content(
        model="gemini-2.5-flash-preview-05-20",
        contents=prompt,
        config=GenerateContentConfig(
            temperature=0.2,
            top_p=0.95,
            top_k=20,
            max_output_tokens=4096,
        ),
    )
    OUT_FILE.write_text(response.text.strip())
    print("✅ repo_summary.txt written")
