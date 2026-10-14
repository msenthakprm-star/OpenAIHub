#!/usr/bin/env python3
"""Daily updater: pulls fresh open-source AI items into data/news.json and data/projects.json.

Sources (no API keys needed): Hugging Face trending models + blog feed, and new
GitHub repos with an open license. Standard library only. It writes JSON data
only; it never edits code. Optional: set LLM_BASE_URL, LLM_MODEL and LLM_API_KEY
(any OpenAI-compatible endpoint) to have a model write one-line summaries.
"""
import datetime as dt, email.utils, html, json, os, re, urllib.parse, urllib.request
import xml.etree.ElementTree as ET

DATA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
TODAY = dt.date.today()
TOPICS = ["llm", "generative-ai", "ai-agent"]


def get(url, headers=None):
    h = {"User-Agent": "open-ai-hub-updater", "Accept": "*/*"}
    h.update(headers or {})
    with urllib.request.urlopen(urllib.request.Request(url, headers=h), timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def clean(t, n=230):
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t or ""))).strip()
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0] + "..."


def summarize(text):
    base, model, key = (os.environ.get(k) for k in ("LLM_BASE_URL", "LLM_MODEL", "LLM_API_KEY"))
    if not (base and model and key and text):
        return text
    try:
        body = json.dumps({"model": model, "temperature": 0.2, "messages": [{"role": "user",
            "content": "Write one plain sentence (max 30 words) describing this open-source AI "
                       "item. Use only the text given.\n\n" + text}]}).encode()
        req = urllib.request.Request(base.rstrip("/") + "/chat/completions", data=body, headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + key})
        with urllib.request.urlopen(req, timeout=60) as r:
            return clean(json.load(r)["choices"][0]["message"]["content"], 260) or text
    except Exception:
        return text


def hf_models():
    out = []
    for m in json.loads(get("https://huggingface.co/api/models?sort=trendingScore&limit=10")):
        mid = m.get("id")
        if mid:
            out.append({"date": TODAY.isoformat(), "tag": "Trending", "url": "https://huggingface.co/" + mid,
                        "title": "Trending on Hugging Face: " + mid,
                        "summary": f"Task: {m.get('pipeline_tag') or 'n/a'}. {m.get('likes', 0)} likes, "
                                   f"{m.get('downloads', 0)} downloads."})
    return out


def hf_blog():
    root, out = ET.fromstring(get("https://huggingface.co/blog/feed.xml")), []
    atom = "{http://www.w3.org/2005/Atom}"
    for it in (root.iter("item") or []):
        title, link = it.findtext("title"), it.findtext("link")
        try:
            d = email.utils.parsedate_to_datetime(it.findtext("pubDate")).date()
        except Exception:
            d = TODAY
        if title and link and (TODAY - d).days <= 30:
            out.append({"date": d.isoformat(), "tag": "Blog", "url": link.strip(), "title": clean(title, 120),
                        "summary": summarize(clean(it.findtext("description")))})
    for it in root.iter(atom + "entry"):
        title, link = it.findtext(atom + "title"), (it.find(atom + "link") or {}).get("href")
        d = (it.findtext(atom + "updated") or TODAY.isoformat())[:10]
        if title and link:
            out.append({"date": d, "tag": "Blog", "url": link, "title": clean(title, 120),
                        "summary": summarize(clean(it.findtext(atom + "summary")))})
    return out[:10]


def gh_repos():
    headers = {"Accept": "application/vnd.github+json"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    since, news, projects = (TODAY - dt.timedelta(days=14)).isoformat(), [], []
    for topic in TOPICS:
        q = f"topic:{topic} created:>{since} stars:>=100"
        url = "https://api.github.com/search/repositories?" + urllib.parse.urlencode(
            {"q": q, "sort": "stars", "order": "desc", "per_page": 10})
        for r in json.loads(get(url, headers)).get("items", []):
            lic = (r.get("license") or {}).get("spdx_id")
            if not lic or lic == "NOASSERTION" or not r.get("description"):
                continue
            desc = summarize(clean(r["description"]))
            news.append({"date": r["created_at"][:10], "tag": "New repo", "url": r["html_url"],
                         "title": f"New repo: {r['full_name']} ({r['stargazers_count']} stars)", "summary": desc})
            projects.append({"name": r["name"], "url": r["full_name"], "license": lic, "desc": desc,
                             "usage": f"git clone {r['clone_url']}\n# see the README for setup",
                             "found": TODAY.isoformat()})
    return news, projects


def read(name):
    try:
        return json.load(open(os.path.join(DATA, name), encoding="utf-8"))
    except Exception:
        return []


def merge(old, new, key):
    seen = {key(x) for x in old}
    return old + [x for x in new if key(x) not in seen and not seen.add(key(x))]


def main():
    news_new, proj_new = [], []
    for label, fn in (("HF trending", hf_models), ("HF blog", hf_blog), ("GitHub", gh_repos)):
        try:
            res = fn()
            if label == "GitHub":
                news_new += res[0]; proj_new += res[1]
            else:
                news_new += res
        except Exception as e:
            print(f"WARNING: {label} failed: {e}")
    news = merge(read("news.json"), news_new, lambda x: x["url"])
    projects = merge(read("projects.json"), proj_new, lambda x: x["url"])
    news.sort(key=lambda x: x["date"], reverse=True)
    projects.sort(key=lambda x: x.get("found", ""), reverse=True)
    os.makedirs(DATA, exist_ok=True)
    for name, items, cap in (("news.json", news, 300), ("projects.json", projects, 40)):
        json.dump(items[:cap], open(os.path.join(DATA, name), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"Done. {len(news_new)} candidate news, {len(proj_new)} candidate projects.")


if __name__ == "__main__":
    main()
