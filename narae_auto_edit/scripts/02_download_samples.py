#!/usr/bin/env python3
"""
Step 2: 분석용 샘플 영상 다운로드
채널 영상 중 대표 샘플을 선정해 오디오+영상을 다운로드합니다.
"""

import json
import subprocess
import sys
from pathlib import Path

ANALYSIS_DIR = Path(__file__).parent.parent / "analysis"
DOWNLOAD_DIR = Path(__file__).parent.parent / "downloads"
CHANNEL_FILE = ANALYSIS_DIR / "channel_videos.json"

# 분석할 샘플 수 (너무 많으면 시간이 오래 걸림)
SAMPLE_COUNT = 5


def select_samples(videos: list[dict], count: int) -> list[dict]:
    """
    다양한 길이의 영상을 선택해 패턴 분석의 대표성을 높입니다.
    """
    valid = [v for v in videos if v.get("duration") and v.get("id")]
    valid.sort(key=lambda v: v["duration"])

    if len(valid) <= count:
        return valid

    # 짧은/중간/긴 영상 골고루 선택
    indices = [int(i * (len(valid) - 1) / (count - 1)) for i in range(count)]
    return [valid[i] for i in indices]


def download_video(video: dict, output_dir: Path) -> Path | None:
    output_dir.mkdir(parents=True, exist_ok=True)
    video_id = video["id"]
    url = video["url"]
    title = video["title"][:50].replace("/", "-").replace("\\", "-")

    out_template = str(output_dir / f"{video_id}_%(title).50s.%(ext)s")

    # 이미 다운로드된 파일 확인
    existing = list(output_dir.glob(f"{video_id}_*"))
    if existing:
        print(f"  이미 존재: {existing[0].name}")
        return existing[0]

    print(f"  다운로드 중: [{video['duration']//60}:{video['duration']%60:02d}] {title}")

    cmd = [
        "yt-dlp",
        "-f", "bestvideo[height<=720]+bestaudio/best[height<=720]",
        "--merge-output-format", "mp4",
        "-o", out_template,
        "--no-playlist",
        "--no-warnings",
        url,
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        print(f"  오류: {result.stderr[:200]}", file=sys.stderr)
        return None

    downloaded = list(output_dir.glob(f"{video_id}_*"))
    if downloaded:
        print(f"  완료: {downloaded[0].name}")
        return downloaded[0]

    return None


def download_samples():
    if not CHANNEL_FILE.exists():
        print("채널 영상 목록이 없습니다. 먼저 01_fetch_channel.py를 실행하세요.")
        sys.exit(1)

    with open(CHANNEL_FILE, encoding="utf-8") as f:
        data = json.load(f)

    videos = data["videos"]
    print(f"전체 {len(videos)}개 영상 중 {SAMPLE_COUNT}개 샘플 선택")

    samples = select_samples(videos, SAMPLE_COUNT)
    print("\n선택된 샘플:")
    for v in samples:
        dur = f"{v['duration']//60}:{v['duration']%60:02d}" if v.get("duration") else "?:??"
        print(f"  [{dur}] {v['title'][:60]}")

    print(f"\n다운로드 시작 ({DOWNLOAD_DIR})")
    downloaded = []
    for v in samples:
        path = download_video(v, DOWNLOAD_DIR)
        if path:
            downloaded.append({"video": v, "path": str(path)})

    # 다운로드 결과 저장
    result_file = ANALYSIS_DIR / "downloaded_samples.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(downloaded, f, ensure_ascii=False, indent=2)

    print(f"\n{len(downloaded)}/{len(samples)}개 다운로드 완료")
    print(f"결과 저장: {result_file}")
    return downloaded


if __name__ == "__main__":
    download_samples()
