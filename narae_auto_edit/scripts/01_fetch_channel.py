#!/usr/bin/env python3
"""
Step 1: 채널 영상 목록 수집
채널 URL에서 모든 영상 메타데이터를 가져와 JSON으로 저장합니다.
"""

import json
import subprocess
import sys
from pathlib import Path
from datetime import datetime

CHANNEL_URL = "https://youtube.com/@leenaraek"
OUTPUT_DIR = Path(__file__).parent.parent / "analysis"
OUTPUT_FILE = OUTPUT_DIR / "channel_videos.json"


def fetch_channel_videos(channel_url: str, max_videos: int = None) -> list[dict]:
    cmd = [
        "yt-dlp",
        "--flat-playlist",
        "--dump-single-json",
        "--no-warnings",
        channel_url,
    ]
    if max_videos:
        cmd += ["--playlist-end", str(max_videos)]

    print(f"채널 영상 목록 수집 중: {channel_url}")
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)

    if result.returncode != 0:
        print(f"오류: {result.stderr}", file=sys.stderr)
        sys.exit(1)

    data = json.loads(result.stdout)
    entries = data.get("entries", [])
    print(f"총 {len(entries)}개 영상 발견")
    return entries


def save_video_list(entries: list[dict], output_file: Path):
    output_file.parent.mkdir(parents=True, exist_ok=True)

    videos = []
    for e in entries:
        if not e:
            continue
        videos.append({
            "id": e.get("id"),
            "title": e.get("title"),
            "url": f"https://youtube.com/watch?v={e.get('id')}",
            "duration": e.get("duration"),
            "view_count": e.get("view_count"),
            "upload_date": e.get("upload_date"),
            "thumbnail": e.get("thumbnail"),
        })

    result = {
        "channel": CHANNEL_URL,
        "fetched_at": datetime.now().isoformat(),
        "total_count": len(videos),
        "videos": videos,
    }

    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"저장 완료: {output_file}")
    return videos


def print_summary(videos: list[dict]):
    print("\n=== 채널 영상 요약 ===")
    print(f"총 영상 수: {len(videos)}")

    durations = [v["duration"] for v in videos if v.get("duration")]
    if durations:
        avg_dur = sum(durations) / len(durations)
        print(f"평균 영상 길이: {avg_dur/60:.1f}분")
        print(f"최단 영상: {min(durations)/60:.1f}분")
        print(f"최장 영상: {max(durations)/60:.1f}분")

    print("\n최근 영상 5개:")
    for v in videos[:5]:
        dur = f"{v['duration']//60}:{v['duration']%60:02d}" if v.get("duration") else "?:??"
        print(f"  [{dur}] {v['title']}")


if __name__ == "__main__":
    entries = fetch_channel_videos(CHANNEL_URL)
    videos = save_video_list(entries, OUTPUT_FILE)
    print_summary(videos)
