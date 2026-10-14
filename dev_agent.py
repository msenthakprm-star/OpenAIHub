#!/usr/bin/env python3
"""Developer agent: edits your site file using any OpenAI-compatible LLM.

Works with a local Ollama model (free, no limits) or any hosted free tier
(OpenRouter, Groq, Hugging Face router, ...). Standard library only.

Usage:
  python dev_agent.py "add a Datasets category with 4 projects"
  python dev_agent.py --push "make the header darker"
  python dev_agent.py            # interactive: type a request per line

Settings (environment variables):
  LLM_BASE_URL  default http://localhost:11434/v1   (Ollama)
  LLM_MODEL     default qwen2.5-coder:7b
  LLM_API_KEY   default "ollama" (set a real key for hosted services)
"""
import argparse, json, os, re, shutil, subprocess, sys, time
import urllib.error, urllib.request

BASE = os.environ.get("LLM_BASE_URL", "http://localhost:11434/v1").rstrip("/")
MODEL = os.environ.get("LLM_MODEL", "qwen2.5-coder:7b")
KEY = os.environ.get("LLM_API_KEY", "ollama")

SYSTEM = """You are a careful front-end developer editing one self-contained HTML file.
Reply ONLY with edit blocks in exactly this format, no other text:

<<<<<<< SEARCH
exact existing text copied from the file (must appear exactly once)
=======
new text that replaces it
>>>>>>> REPLACE

Rules: keep every existing feature working; keep CSS and JS inline in the one file;
make the smallest edits that satisfy the request; use several small blocks rather
than one large one; never leave the SEARCH text empty or ambiguous."""

BLOCK = re.compile(r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n?>>>>>>> REPLACE", re.S)


def chat(messages):
    body = json.dumps({"model": MODEL, "messages": messages, "temperature": 0.2}).encode()
    req = urllib.request.Request(
        BASE + "/chat/completions", data=body,
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError) as e:
        sys.exit(f"Could not get a reply from the LLM at {BASE}: {e}")


def apply_blocks(text, reply):
    blocks = BLOCK.findall(reply)
    if not blocks:
        return text, ["No SEARCH/REPLACE blocks found in your reply."]
    errors = []
    for i, (old, new) in enumerate(blocks, 1):
        n = text.count(old)
        if n != 1:
            errors.append(f"Block {i}: SEARCH text matched {n} times; it must match exactly once.")
        else:
            text = text.replace(old, new)
    return text, errors


def run(request, path, push):
    original = open(path, encoding="utf-8").read()
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"FILE:\n{original}\n\nREQUEST: {request}"},
    ]
    for _ in range(3):
        reply = chat(messages)
        updated, errors = apply_blocks(original, reply)
        if not errors:
            break
        messages += [
            {"role": "assistant", "content": reply},
            {"role": "user", "content": "Fix these problems and resend ALL blocks "
             "against the ORIGINAL file:\n" + "\n".join(errors)},
        ]
    else:
        sys.exit("Gave up after 3 attempts: " + "; ".join(errors))

    if "</html>" not in updated or "<script" not in updated:
        sys.exit("Result looks broken (missing </html> or <script>); file left unchanged.")

    backup = f"{path}.{time.strftime('%Y%m%d%H%M%S')}.bak"
    shutil.copy(path, backup)
    open(path, "w", encoding="utf-8").write(updated)
    print(f"Updated {path} (backup: {backup}). Open it in a browser to check.")

    if push:
        try:
            subprocess.run(["git", "add", path], check=True)
            subprocess.run(["git", "commit", "-m", "dev agent: " + request[:60]], check=True)
            subprocess.run(["git", "push"], check=True)
        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            print("Saved locally, but git push failed:", e)


def main():
    ap = argparse.ArgumentParser(description="Site developer agent")
    ap.add_argument("request", nargs="*")
    ap.add_argument("--file", default="index.html")
    ap.add_argument("--push", action="store_true", help="git add, commit and push after editing")
    a = ap.parse_args()
    if a.request:
        run(" ".join(a.request), a.file, a.push)
        return
    print(f"Model {MODEL} at {BASE}. Type a request, or press Enter on an empty line to quit.")
    while True:
        r = input("request> ").strip()
        if not r:
            break
        run(r, a.file, a.push)


if __name__ == "__main__":
    main()
