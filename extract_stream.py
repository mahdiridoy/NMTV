#!/usr/bin/env python3
"""
YouTube Live -> M3U converter.

Reads sources.txt (one channel/live link per line, optional "Name | URL" format),
resolves each to a live .m3u8 stream URL using yt-dlp, and writes playlist.m3u.

Run manually:
    python extract_stream.py

Designed to run on a schedule via GitHub Actions (see .github/workflows/update_playlist.yml).
"""

import sys
import re
from pathlib import Path
from urllib.parse import urlparse, urlencode, parse_qs, urlunparse

try:
    import yt_dlp
except ImportError:
    print("yt-dlp is not installed. Run: pip install yt-dlp", file=sys.stderr)
    sys.exit(1)

SOURCES_FILE = Path("sources.txt")
OUTPUT_FILE  = Path("playlist.m3u")

# Use iOS player client to bypass GitHub Actions bot-detection without cookies.
# Fall back through android then web so at least one client succeeds.
YDL_OPTS = {
    "quiet":         True,
    "no_warnings":   True,
    "skip_download": True,
    "noplaylist":    True,
    # Best available m3u8 stream; mp4 fallback for non-live
    "format": "best[protocol^=m3u8]/bestvideo[protocol^=m3u8]+bestaudio[protocol^=m3u8]/best",
    # iOS client avoids the "Sign in to confirm you're not a bot" error on CI runners
    "extractor_args": {
        "youtube": {
            "player_client": ["ios", "android", "web"],
        }
    },
    # Raise an error on bot-check pages rather than hanging
    "socket_timeout": 30,
}


def strip_tracking_params(url: str) -> str:
    """Remove ?si= and other tracking params YouTube appends to shared links."""
    parsed = urlparse(url)
    qs = parse_qs(parsed.query, keep_blank_values=True)
    # Keep only params that affect which video/stream is loaded
    keep = {k: v for k, v in qs.items() if k not in ("si", "feature", "app", "utm_source",
                                                        "utm_medium", "utm_campaign")}
    clean = parsed._replace(query=urlencode(keep, doseq=True))
    return urlunparse(clean)


def parse_sources(path: Path):
    """Parse sources.txt into a list of (name_or_none, url) tuples."""
    entries = []
    if not path.exists():
        print(f"Source file not found: {path}", file=sys.stderr)
        return entries

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if "|" in line:
            name, url = line.split("|", 1)
            name = name.strip()
            url  = url.strip()
        else:
            name = None
            url  = line.strip()

        if url:
            url = strip_tracking_params(url)
            entries.append((name or None, url))

    return entries


def resolve_stream(url: str):
    """
    Use yt-dlp to resolve a channel/live/video URL into:
      - title      (str)
      - stream_url (str, the actual .m3u8 manifest URL)
    Returns (None, None) on failure (channel offline, bot-block, etc.).
    """
    try:
        with yt_dlp.YoutubeDL(YDL_OPTS) as ydl:
            info = ydl.extract_info(url, download=False)
    except yt_dlp.utils.DownloadError as exc:
        print(f"  -> FAILED: {exc}", file=sys.stderr)
        return None, None
    except Exception as exc:
        print(f"  -> FAILED (unexpected): {exc}", file=sys.stderr)
        return None, None

    if info is None:
        return None, None

    # Channel "/live" pages sometimes return a playlist wrapper — unwrap it
    if "entries" in info:
        info = next((e for e in (info.get("entries") or []) if e), None)
        if info is None:
            return None, None

    live_status = info.get("live_status", "")
    is_live = info.get("is_live") or live_status in ("is_live", "is_upcoming")
    if not is_live:
        print(f"  -> NOT LIVE right now (live_status={live_status!r}): {url}", file=sys.stderr)
        return None, None

    title      = info.get("title", "Untitled Stream")
    stream_url = info.get("url")

    # Fallback: pick best m3u8 from formats list
    if not stream_url:
        formats = info.get("formats") or []
        m3u8_fmts = [
            f for f in formats
            if f.get("protocol", "").startswith("m3u8") and f.get("url")
        ]
        if m3u8_fmts:
            # prefer higher quality (last in list is usually best with yt-dlp ordering)
            stream_url = m3u8_fmts[-1]["url"]

    if not stream_url:
        print(f"  -> No playable URL found: {url}", file=sys.stderr)
        return None, None

    return title, stream_url


def sanitize_name(name: str) -> str:
    return re.sub(r"\s+", " ", name).strip()


def build_playlist(entries):
    lines = ["#EXTM3U"]
    success_count = 0

    for custom_name, url in entries:
        label = custom_name or url
        print(f"Checking: {label}")
        title, stream_url = resolve_stream(url)

        if not stream_url:
            continue

        display_name = sanitize_name(custom_name or title)
        lines.append(f'#EXTINF:-1 tvg-name="{display_name}",{display_name}')
        lines.append(stream_url)
        success_count += 1
        print(f"  -> OK: {display_name}")

    return lines, success_count


def main():
    entries = parse_sources(SOURCES_FILE)
    if not entries:
        print("No sources found in sources.txt. Nothing to do.", file=sys.stderr)
        sys.exit(0)

    print(f"Found {len(entries)} source link(s). Resolving live streams...\n")
    lines, success_count = build_playlist(entries)

    OUTPUT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\nDone. {success_count}/{len(entries)} channel(s) live → {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
