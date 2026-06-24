#!/usr/bin/env python3
"""
Step 6: FCPXML 생성
편집된 영상과 자막 데이터를 Final Cut Pro XML (FCPXML 1.11) 형식으로 출력합니다.
Final Cut Pro에서 직접 열 수 있습니다.
"""

import json
import subprocess
import sys
import re
from pathlib import Path
from xml.etree import ElementTree as ET
from xml.dom import minidom
from fractions import Fraction
from dataclasses import dataclass

ANALYSIS_DIR = Path(__file__).parent.parent / "analysis"
OUTPUT_DIR = Path(__file__).parent.parent / "output"


# FCPXML 타임베이스 (Final Cut Pro 기본)
TIMEBASE = 30000
TIMEBASE_DEN = 1001  # 29.97 fps = 30000/1001


def seconds_to_fcptime(seconds: float) -> str:
    """초를 FCPXML rational time 문자열로 변환 (예: '90090/30000s')"""
    # 정수 프레임 단위로 반올림 (drop-frame 호환)
    frame_rate = Fraction(TIMEBASE, TIMEBASE_DEN)
    frames = round(seconds * frame_rate)
    numerator = frames * TIMEBASE_DEN
    return f"{numerator}/{TIMEBASE}s"


def get_video_info(video_path: Path) -> dict:
    """ffmpeg으로 영상 메타데이터 추출"""
    # ffmpeg -v quiet -print_format json -show_streams -show_format 은 ffprobe 전용
    # ffmpeg 바이너리에서는 stderr에 정보가 출력되므로 파싱
    cmd = [
        "ffmpeg", "-v", "quiet", "-i", str(video_path),
        "-print_format", "json", "-show_streams", "-show_format",
        "-f", "null", "-",
    ]
    # 먼저 ffprobe 방식 시도 (Mac 환경에서는 ffprobe 있음)
    probe_cmd = [
        "ffprobe", "-v", "quiet",
        "-print_format", "json",
        "-show_streams", "-show_format",
        str(video_path),
    ]
    result = subprocess.run(probe_cmd, capture_output=True, text=True, timeout=30)

    if result.returncode != 0 or not result.stdout.strip():
        # ffprobe 없으면 ffmpeg stderr 파싱
        result2 = subprocess.run(
            ["ffmpeg", "-i", str(video_path)],
            capture_output=True, text=True, timeout=30,
        )
        stderr = result2.stderr
        return _parse_ffmpeg_stderr(stderr)

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        result2 = subprocess.run(
            ["ffmpeg", "-i", str(video_path)],
            capture_output=True, text=True, timeout=30,
        )
        return _parse_ffmpeg_stderr(result2.stderr)

    video_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "video"),
        {}
    )
    audio_stream = next(
        (s for s in data.get("streams", []) if s.get("codec_type") == "audio"),
        {}
    )

    fr_str = video_stream.get("r_frame_rate", "30/1")
    try:
        num, den = fr_str.split("/")
        frame_rate = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        frame_rate = 30.0

    duration = float(data.get("format", {}).get("duration", 0))
    width = int(video_stream.get("width", 1920))
    height = int(video_stream.get("height", 1080))
    sample_rate = int(audio_stream.get("sample_rate", 48000))

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "frame_rate": frame_rate,
        "sample_rate": sample_rate,
        "fr_str": fr_str,
    }


def _parse_ffmpeg_stderr(stderr: str) -> dict:
    """ffmpeg -i 출력에서 영상 정보 파싱 (ffprobe 없을 때 폴백)"""
    import re

    duration = 0.0
    m = re.search(r'Duration:\s*(\d+):(\d+):([\d.]+)', stderr)
    if m:
        h, mn, s = int(m.group(1)), int(m.group(2)), float(m.group(3))
        duration = h * 3600 + mn * 60 + s

    width, height = 1920, 1080
    m = re.search(r'(\d{2,5})x(\d{2,5})', stderr)
    if m:
        width, height = int(m.group(1)), int(m.group(2))

    fr_str = "30/1"
    frame_rate = 30.0
    m = re.search(r'(\d+(?:\.\d+)?)\s*(?:fps|tbr)', stderr)
    if m:
        frame_rate = float(m.group(1))
        fr_str = f"{int(frame_rate * 1000)}/1000"

    sample_rate = 48000
    m = re.search(r'(\d{4,6})\s*Hz', stderr)
    if m:
        sample_rate = int(m.group(1))

    return {
        "duration": duration,
        "width": width,
        "height": height,
        "frame_rate": frame_rate,
        "sample_rate": sample_rate,
        "fr_str": fr_str,
    }


def create_fcpxml(
    video_path: Path,
    output_path: Path,
    subtitles: list[dict] = None,
    edit_segments: list[dict] = None,
    project_name: str = None,
) -> Path:
    """
    FCPXML 1.11 파일 생성
    - video_path: 원본 또는 편집된 영상
    - subtitles: [{"start": float, "end": float, "text": str}, ...]
    - edit_segments: [{"start": float, "end": float}, ...] - None이면 전체 영상 사용
    """
    if not video_path.exists():
        raise FileNotFoundError(f"영상 파일 없음: {video_path}")

    info = get_video_info(video_path)
    duration = info["duration"]
    width = info["width"]
    height = info["height"]
    sample_rate = info["sample_rate"]
    fr_str = info.get("fr_str", "30/1")

    if not project_name:
        project_name = video_path.stem

    # 편집 구간이 없으면 전체 영상
    if not edit_segments:
        edit_segments = [{"start": 0.0, "end": duration}]

    total_edit_duration = sum(s["end"] - s["start"] for s in edit_segments)

    # XML 트리 구성
    root = ET.Element("fcpxml", version="1.11")

    # Resources
    resources = ET.SubElement(root, "resources")

    # Format (영상 해상도/프레임레이트)
    format_id = "r1"
    ET.SubElement(resources, "format",
        id=format_id,
        name=f"FFVideoFormat{height}p{fr_str.replace('/', '')}",
        frameDuration=f"{TIMEBASE_DEN}/{TIMEBASE}s",
        width=str(width),
        height=str(height),
        colorSpace="1-1-1 (Rec. 709)",
    )

    # Asset (영상 파일)
    asset_id = "r2"
    asset = ET.SubElement(resources, "asset",
        id=asset_id,
        name=video_path.stem,
        uid=f"narae_{video_path.stem}",
        start="0s",
        duration=seconds_to_fcptime(duration),
        hasVideo="1",
        hasAudio="1",
        audioSources="1",
        audioChannels="2",
        audioRate=str(sample_rate),
        format=format_id,
    )
    ET.SubElement(asset, "media-rep",
        kind="original-media",
        src=video_path.as_uri(),
    )

    # Effect (자막용 텍스트 효과)
    if subtitles:
        ET.SubElement(resources, "effect",
            id="r3",
            name="Basic Title",
            uid=".../Titles.localized/Bumper:Opener.localized/Basic Title.localized/Basic Title.moti",
        )

    # Library > Event > Project
    library = ET.SubElement(root, "library")
    event = ET.SubElement(library, "event", name="Narae Auto Edit")
    project = ET.SubElement(event, "project", name=project_name)

    # Sequence (타임라인)
    sequence = ET.SubElement(project, "sequence",
        duration=seconds_to_fcptime(total_edit_duration),
        format=format_id,
        tcStart="0s",
        tcFormat="NDF",
        audioLayout="stereo",
        audioRate=str(sample_rate),
    )
    spine = ET.SubElement(sequence, "spine")

    # 각 편집 구간을 클립으로 추가
    timeline_offset = 0.0
    ts_counter = [0]  # text-style-def 고유 ID 카운터

    def next_ts_id() -> str:
        ts_counter[0] += 1
        return f"ts{ts_counter[0]}"

    for seg in edit_segments:
        seg_start = seg["start"]
        seg_end = seg["end"]
        seg_dur = seg_end - seg_start

        clip = ET.SubElement(spine, "clip",
            name=video_path.stem,
            offset=seconds_to_fcptime(timeline_offset),
            duration=seconds_to_fcptime(seg_dur),
            start=seconds_to_fcptime(seg_start),
            format=format_id,
            tcFormat="NDF",
        )
        ET.SubElement(clip, "audio-channel-source",
            srcCh="1, 2",
            outCh="L, R",
            role="dialogue",
        )

        # 이 구간에 해당하는 자막 추가
        if subtitles:
            clip_subs = [
                s for s in subtitles
                if s["start"] >= seg_start and s["end"] <= seg_end + 0.1
            ]
            for sub in clip_subs:
                sub_offset_in_clip = sub["start"] - seg_start
                sub_dur = sub["end"] - sub["start"]
                ts_id = next_ts_id()

                title = ET.SubElement(clip, "title",
                    name=sub["text"][:30],
                    lane="1",
                    offset=seconds_to_fcptime(sub_offset_in_clip),
                    duration=seconds_to_fcptime(max(sub_dur, 0.5)),
                    ref="r3",
                    role="titles",
                )
                ET.SubElement(title, "param",
                    name="Text",
                    key="9999/999166631/999166633/2/354",
                    value=sub["text"],
                )
                text_el = ET.SubElement(title, "text")
                text_style = ET.SubElement(text_el, "text-style", ref=ts_id)
                text_style.text = sub["text"]
                ET.SubElement(title, "text-style-def",
                    id=ts_id,
                    font="Apple SD Gothic Neo",
                    fontSize="52",
                    fontFace="Regular",
                    fontColor="1 1 1 1",
                    bold="0",
                    italic="0",
                    alignment="center",
                )

        timeline_offset += seg_dur

    # XML 직렬화 (DOCTYPE 중복 방지)
    xml_str = ET.tostring(root, encoding="unicode", xml_declaration=False)
    pretty = minidom.parseString(xml_str)
    pretty_str = pretty.toprettyxml(indent="  ", encoding=None)
    # minidom이 추가한 xml 선언 제거 후 우리 선언+DOCTYPE 사용
    lines = pretty_str.split("\n")
    if lines[0].startswith("<?xml"):
        lines = lines[1:]
    final_xml = '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n' + "\n".join(lines)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(final_xml)

    print(f"  FCPXML 저장: {output_path.name}")
    return output_path


def load_subtitles_for_video(video_id: str) -> list[dict]:
    """transcriptions.json에서 자막 로드"""
    transcription_file = ANALYSIS_DIR / "transcriptions.json"
    if not transcription_file.exists():
        return []

    with open(transcription_file, encoding="utf-8") as f:
        data = json.load(f)

    for tr in data:
        if tr["video_id"] == video_id:
            return [{"start": s["start"], "end": s["end"], "text": s["text"]}
                    for s in tr.get("segments", [])]
    return []


def generate_fcpxml_for_edited(edited_video: Path, original_video_id: str = None) -> Path:
    """편집된 영상에 대한 FCPXML 생성 (편집 구간 없이 전체 사용)"""
    subtitles = load_subtitles_for_video(original_video_id) if original_video_id else []

    output_path = edited_video.with_suffix(".fcpxml")
    create_fcpxml(
        video_path=edited_video,
        output_path=output_path,
        subtitles=subtitles,
        edit_segments=None,
        project_name=edited_video.stem,
    )
    return output_path


def generate_fcpxml_from_original(
    video_path: Path,
    edit_segments: list[dict],
    subtitles: list[dict],
    output_path: Path,
) -> Path:
    """원본 영상 + 편집 구간 정보로 FCPXML 생성 (영상 재인코딩 없음)"""
    create_fcpxml(
        video_path=video_path,
        output_path=output_path,
        subtitles=subtitles,
        edit_segments=edit_segments,
        project_name=video_path.stem,
    )
    return output_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="FCPXML 생성")
    parser.add_argument("video", help="입력 영상 파일")
    parser.add_argument("--output", "-o", help="출력 FCPXML 경로")
    parser.add_argument("--video-id", help="원본 YouTube 영상 ID (자막 로드용)")
    args = parser.parse_args()

    video_path = Path(args.video)
    if not video_path.exists():
        print(f"파일 없음: {video_path}")
        sys.exit(1)

    out_path = Path(args.output) if args.output else video_path.with_suffix(".fcpxml")
    subtitles = load_subtitles_for_video(args.video_id) if args.video_id else []

    print(f"FCPXML 생성 중: {video_path.name}")
    print(f"자막 수: {len(subtitles)}개")

    result = create_fcpxml(
        video_path=video_path,
        output_path=out_path,
        subtitles=subtitles,
    )
    print(f"완료: {result}")
    print("\nFinal Cut Pro에서 열기: File > Import > XML...")
