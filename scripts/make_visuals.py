#!/usr/bin/env python3
"""
Build visuals.mp4 (1080x1920) for a YouTube Short from stock footage.

Usage:  python visuals.py /data/jobs/<job>

Reads   <job>/script.json   ({"title": ..., "narration": ...})
        optional voice-over audio in the job dir (used to match video length)
Writes  <job>/visuals.mp4, <job>/visual_credits.json, <job>/scenes.json

Env vars
  PIXABAY_API_KEY    (required unless PEXELS_API_KEY is set)
  PEXELS_API_KEY     (recommended: Pexels has real portrait 4K footage)
  ANTHROPIC_API_KEY  (recommended: writes concrete, filmable search queries
                      per scene. Falls back to keyword extraction without it.)
  ANTHROPIC_MODEL    (default: claude-sonnet-5-5)
"""
import json
import math
import os
import re
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

JOB_DIR = Path(sys.argv[1] if len(sys.argv) > 1 else "/data/jobs/test")

PIXABAY_KEY = os.environ.get("PIXABAY_API_KEY", "").strip()
PEXELS_KEY = os.environ.get("PEXELS_API_KEY", "").strip()
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-5-5")

W, H, FPS = 1080, 1920, 30
TARGET_SCENE = 4.0        # average seconds per shot (fast cuts hold attention)
MIN_SCENE, MAX_SCENE = 2.5, 6.0
MAX_SCENES = 12
MAX_UPSCALE = 1.2         # above this, use blurred-background layout, not crop
MIN_RELEVANCE = 0.5       # share of query words that must appear in clip tags
CRF = "17"
UA = "ShortsWorker/2.0"

STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "to", "of", "in", "on", "for",
    "with", "is", "are", "was", "were", "just", "this", "that", "it", "its",
    "how", "why", "what", "new", "after", "from", "has", "have", "will",
    "could", "their", "they", "you", "your", "about", "into", "than", "more",
    "over", "under", "up", "down", "as", "at", "by", "be", "been", "can",
    "not", "all", "now", "out", "who", "when", "where", "also", "some",
    "get", "got", "one", "two", "may", "might", "would", "should", "said",
    "says", "say", "like", "very", "much", "many", "most", "other", "then",
    # abstract news words that never describe footage
    "breaking", "report", "reports", "news", "update", "latest", "according",
    "reportedly", "announced", "announces", "today", "year", "week",
}


# --------------------------------------------------------------------------
# text helpers
# --------------------------------------------------------------------------
def keywords(text, limit=8):
    words = re.findall(r"[a-zA-Z0-9]+", (text or "").lower())
    result = []
    for word in words:
        if len(word) > 2 and word not in STOPWORDS and word not in result:
            result.append(word)
        if len(result) >= limit:
            break
    return result


def stem(word):
    word = word.lower()
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
        return word[:-1]
    return word


def http_get_json(url, headers=None, timeout=40):
    req = urllib.request.Request(url, headers={"User-Agent": UA, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


# --------------------------------------------------------------------------
# timing: how long should the video be?
# --------------------------------------------------------------------------
def probe_duration(path):
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(path)],
            check=True, capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return float(out)
    except Exception:
        return None


def get_total_duration(script):
    names = []
    if isinstance(script.get("audio"), str):
        names.append(script["audio"])
    names += [
        "voice.mp3", "voiceover.mp3", "narration.mp3", "audio.mp3",
        "voice.wav", "voiceover.wav", "narration.wav", "audio.wav",
        "voice.m4a",
    ]
    for name in names:
        path = JOB_DIR / name
        if path.exists():
            dur = probe_duration(path)
            if dur:
                print(f"Matching voice-over length: {dur:.1f}s ({name})")
                return dur
    if isinstance(script.get("duration"), (int, float)):
        return float(script["duration"])
    words = len((script.get("narration") or "").split())
    est = max(8.0, words / 2.6)  # ~156 words per minute
    print(f"No audio found, estimating {est:.1f}s from word count")
    return est


# --------------------------------------------------------------------------
# scene planning: the biggest relevance win
# --------------------------------------------------------------------------
def llm_scenes(script, n):
    """Ask Claude for concrete, filmable stock-footage queries per scene."""
    if not ANTHROPIC_KEY:
        return None
    prompt = (
        "You are a video editor choosing stock footage for a vertical "
        "YouTube Short.\n\n"
        f"Title: {script.get('title', '')}\n"
        f"Narration: {script.get('narration', '')}\n\n"
        f"Split the narration into {n} consecutive scenes, in order, "
        "covering all of it. For each scene return:\n"
        '- "text": the exact narration words for that scene\n'
        '- "queries": 3 stock-footage search queries, each 1-3 plain words, '
        "describing something concrete and filmable (objects, places, "
        "actions, types of people). Never abstract concepts, people's names, "
        "or obscure brands. Order them from most specific to most general "
        "but still visually related to the scene.\n\n"
        'Return only JSON: {"scenes":[{"text":"...","queries":["...","...","..."]}]}'
    )
    body = json.dumps({
        "model": ANTHROPIC_MODEL,
        "max_tokens": 2000,
        "messages": [{"role": "user", "content": prompt}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": ANTHROPIC_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
            "User-Agent": UA,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data["content"][0]["text"]
        text = text[text.index("{"): text.rindex("}") + 1]
        scenes = json.loads(text)["scenes"]
        cleaned = []
        for s in scenes:
            queries = [q.strip() for q in s.get("queries", [])
                       if isinstance(q, str) and q.strip()][:3]
            if s.get("text") and queries:
                cleaned.append({"text": s["text"], "queries": queries})
        return cleaned or None
    except Exception as exc:
        print(f"LLM scene planning failed, using keyword fallback: {exc}")
        return None


def heuristic_queries(chunk, title):
    kw = keywords(chunk, 8)
    qs = []
    if len(kw) >= 2:
        qs.append(" ".join(kw[:2]))
    if len(kw) >= 4:
        qs.append(" ".join(kw[2:4]))
    tk = keywords(title, 3)
    if tk:
        qs.append(" ".join(tk[:2]))
    if kw:
        qs.append(kw[0])
    out = []
    for q in qs:
        if q and q not in out:
            out.append(q)
    return out[:4]


def heuristic_scenes(script, n):
    words = (script.get("narration") or script.get("title") or "").split()
    if not words:
        return []
    size = max(1, math.ceil(len(words) / n))
    scenes = []
    for i in range(0, len(words), size):
        chunk = " ".join(words[i:i + size])
        scenes.append({
            "text": chunk,
            "queries": heuristic_queries(chunk, script.get("title", "")),
        })
    return [s for s in scenes if s["queries"]]


def plan_scenes(script, total):
    n = max(3, min(MAX_SCENES, round(total / TARGET_SCENE)))
    scenes = llm_scenes(script, n) or heuristic_scenes(script, n)
    if not scenes:
        raise RuntimeError("Could not plan scenes: empty title/narration?")

    # allocate time proportional to words spoken in each scene
    weights = [max(1, len(s["text"].split())) for s in scenes]
    raw = [total * w / sum(weights) for w in weights]
    secs = [max(MIN_SCENE, min(MAX_SCENE, r)) for r in raw]
    factor = total / sum(secs)
    secs = [s * factor for s in secs]
    for scene, s in zip(scenes, secs):
        scene["seconds"] = round(s, 2)
    scenes[-1]["seconds"] = round(
        scenes[-1]["seconds"] + (total - sum(s["seconds"] for s in scenes)), 2
    )
    return scenes


# --------------------------------------------------------------------------
# providers -> normalised candidates
# --------------------------------------------------------------------------
def pixabay_candidates(query):
    if not PIXABAY_KEY:
        return []
    params = urllib.parse.urlencode({
        "key": PIXABAY_KEY,
        "q": query[:100],
        "per_page": 30,
        "safesearch": "true",
        "video_type": "all",
        "min_width": 1080,
        "min_height": 1080,
        "order": "popular",
    })
    hits = http_get_json("https://pixabay.com/api/videos/?" + params).get("hits", [])
    out = []
    for hit in hits:
        best = None
        for v in (hit.get("videos") or {}).values():
            if v.get("url") and v.get("width") and v.get("height"):
                px = v["width"] * v["height"]
                if best is None or px > best[0]:
                    best = (px, v)
        if not best:
            continue
        v = best[1]
        pop = (min(hit.get("likes", 0), 100) / 100
               + min(hit.get("downloads", 0), 5000) / 5000)
        out.append({
            "provider": "pixabay",
            "key": f"pixabay:{hit.get('id')}",
            "url": v["url"],
            "width": v["width"],
            "height": v["height"],
            "duration": hit.get("duration", 0),
            "words": set(keywords(hit.get("tags", ""), 40)),
            "tags": hit.get("tags", ""),
            "page_url": hit.get("pageURL"),
            "creator": hit.get("user"),
            "popularity": pop,
        })
    return out


def pexels_candidates(query):
    if not PEXELS_KEY:
        return []
    params = urllib.parse.urlencode({
        "query": query[:100],
        "orientation": "portrait",
        "per_page": 30,
    })
    data = http_get_json(
        "https://api.pexels.com/videos/search?" + params,
        headers={"Authorization": PEXELS_KEY},
    )
    out = []
    for vid in data.get("videos", []):
        files = [f for f in vid.get("video_files", [])
                 if f.get("file_type") == "video/mp4" and f.get("link")
                 and f.get("width") and f.get("height")]
        if not files:
            continue
        f = max(files, key=lambda x: x["width"] * x["height"])
        # Pexels has no tags; the URL slug describes the clip
        slug = (vid.get("url") or "").rstrip("/").split("/")[-1]
        slug = re.sub(r"-\d+$", "", slug).replace("-", " ")
        out.append({
            "provider": "pexels",
            "key": f"pexels:{vid.get('id')}",
            "url": f["link"],
            "width": f["width"],
            "height": f["height"],
            "duration": vid.get("duration", 0),
            "words": set(keywords(slug, 40)),
            "tags": slug,
            "page_url": vid.get("url"),
            "creator": (vid.get("user") or {}).get("name"),
            "popularity": 0.5,
        })
    return out


_search_cache = {}


def candidates_for(query):
    if query in _search_cache:
        return _search_cache[query]
    results = []
    for fn in (pixabay_candidates, pexels_candidates):
        try:
            results += fn(query)
        except Exception as exc:
            print(f"  {fn.__name__} failed for '{query}': {exc}")
        time.sleep(0.25)  # stay well inside rate limits
    _search_cache[query] = results
    return results


# --------------------------------------------------------------------------
# scoring and selection
# --------------------------------------------------------------------------
def usable(c):
    """Hard quality gate. Landscape crops lose most pixels, so be strict."""
    w, h = c["width"], c["height"]
    if c["duration"] < 3:
        return False
    if h > w:                       # portrait: needs full 1080 width
        return w >= 1080
    return h >= 1080 and w >= 1920  # landscape: at least Full HD


def quality_bonus(c):
    w, h = c["width"], c["height"]
    if h > w:
        return 8                    # native vertical = sharpest result
    return 4 if h >= 2160 else 0    # 4K landscape crops almost 1:1


def relevance(c, terms):
    if not terms:
        return 0.0
    words = {stem(w) for w in c["words"]}
    return sum(1 for t in terms if stem(t) in words) / len(terms)


def rank_for_scene(scene):
    best = {}
    for rank, query in enumerate(scene["queries"]):
        terms = keywords(query, 6)
        for c in candidates_for(query):
            if not usable(c):
                continue
            rel = relevance(c, terms)
            if rel <= 0:
                continue
            score = (rel * 40 + quality_bonus(c) + c["popularity"] * 2
                     - rank * 3
                     + (2 if c["duration"] >= scene["seconds"] else 0))
            prev = best.get(c["key"])
            if prev is None or score > prev["score"]:
                best[c["key"]] = {**c, "score": score, "rel": rel,
                                  "query": query}
    return sorted(best.values(), key=lambda x: x["score"], reverse=True)


def pick(ranked, used):
    for min_rel, allow_reuse in ((MIN_RELEVANCE, False), (0.01, False),
                                 (0.01, True)):
        for c in ranked:
            if c["rel"] >= min_rel and (allow_reuse or c["key"] not in used):
                return c
    return None


# --------------------------------------------------------------------------
# download + render
# --------------------------------------------------------------------------
def download(url, dest):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as f:
        while chunk := resp.read(1 << 20):
            f.write(chunk)


def build_filter(w, h):
    grade = "eq=contrast=1.04:saturation=1.08"
    if max(W / w, H / h) <= MAX_UPSCALE:
        vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,"
              f"crop={W}:{H},setsar=1,fps={FPS},{grade},format=yuv420p")
        return vf, "fill"
    # Too low-res to crop-and-zoom without going soft: keep the full frame
    # sharp over a blurred, darkened copy of itself.
    vf = (f"split=2[bg][fg];"
          f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,"
          f"crop={W}:{H},boxblur=30:3,eq=brightness=-0.08[b];"
          f"[fg]scale={W}:-2:flags=lanczos[f];"
          f"[b][f]overlay=(W-w)/2:(H-h)/2,setsar=1,fps={FPS},{grade},"
          f"format=yuv420p")
    return vf, "blurpad"


def render_scene(source, dest, w, h, clip_dur, offset, seconds):
    vf, layout = build_filter(w, h)
    need_loop = False
    if clip_dur and offset + seconds > clip_dur - 0.1:
        offset = 0.0
        need_loop = seconds > clip_dur - 0.1
    cmd = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    if need_loop:
        cmd += ["-stream_loop", "-1"]
    cmd += [
        "-ss", f"{offset:.2f}", "-i", str(source), "-t", f"{seconds:.3f}",
        "-vf", vf, "-an",
        "-c:v", "libx264", "-preset", "slow", "-crf", CRF,
        "-pix_fmt", "yuv420p", "-video_track_timescale", "15360",
        "-movflags", "+faststart", str(dest),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
    return layout


def main():
    if not (PIXABAY_KEY or PEXELS_KEY):
        raise RuntimeError("Set PIXABAY_API_KEY and/or PEXELS_API_KEY.")

    with (JOB_DIR / "script.json").open(encoding="utf-8") as f:
        script = json.load(f)

    total = get_total_duration(script)
    scenes = plan_scenes(script, total)
    (JOB_DIR / "scenes.json").write_text(
        json.dumps(scenes, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Planned {len(scenes)} scenes for {total:.1f}s")

    assets = JOB_DIR / "assets"
    assets.mkdir(parents=True, exist_ok=True)

    used = set()
    offsets = {}
    rendered, credits = [], []

    for i, scene in enumerate(scenes, 1):
        print(f"\nScene {i}/{len(scenes)} ({scene['seconds']}s): {scene['text'][:70]}")
        print(f"  queries: {scene['queries']}")
        ranked = rank_for_scene(scene)
        choice = pick(ranked, used)
        if not choice:
            print("  no relevant clip found, skipping this scene")
            continue

        source = assets / f"source_{i}.mp4"
        dest = assets / f"scene_{i}.mp4"
        try:
            print(f"  using {choice['key']} rel={choice['rel']:.2f} "
                  f"{choice['width']}x{choice['height']} "
                  f"query='{choice['query']}' tags='{choice['tags'][:60]}'")
            download(choice["url"], source)
            offset = offsets.get(choice["key"], 0.0)
            layout = render_scene(source, dest, choice["width"],
                                  choice["height"], choice["duration"],
                                  offset, scene["seconds"])
            offsets[choice["key"]] = offset + scene["seconds"]
            used.add(choice["key"])
            rendered.append(dest)
            credits.append({
                "scene": i,
                "text": scene["text"],
                "provider": choice["provider"],
                "id": choice["key"],
                "query": choice["query"],
                "relevance": round(choice["rel"], 2),
                "tags": choice["tags"],
                "source_url": choice["page_url"],
                "creator": choice["creator"],
                "source_size": f"{choice['width']}x{choice['height']}",
                "layout": layout,
            })
        except Exception as exc:
            print(f"  failed: {exc}")
            dest.unlink(missing_ok=True)
        finally:
            source.unlink(missing_ok=True)

    if not rendered:
        raise RuntimeError(
            "No relevant clips found. Add PEXELS_API_KEY and/or "
            "ANTHROPIC_API_KEY, or make the narration more concrete.")

    concat_file = assets / "concat.txt"
    with concat_file.open("w", encoding="utf-8") as f:
        for clip in rendered:
            safe = str(clip.resolve()).replace("'", "'\\''")
            f.write(f"file '{safe}'\n")

    output = JOB_DIR / "visuals.mp4"
    # Stream copy: every scene already has identical encode settings, so
    # re-encoding here would only add a second generation of quality loss.
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat_file),
        "-an", "-c", "copy", "-movflags", "+faststart", str(output),
    ], check=True, timeout=300)

    (JOB_DIR / "visual_credits.json").write_text(
        json.dumps(credits, indent=2, ensure_ascii=False), encoding="utf-8")

    final = probe_duration(output)
    print(f"\nCreated {output}: {len(rendered)}/{len(scenes)} scenes, "
          f"{final:.1f}s (target {total:.1f}s)")


if __name__ == "__main__":
    main()