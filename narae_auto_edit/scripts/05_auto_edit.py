#!/usr/bin/env python3
"""
Step 5: 자동 컷 편집
패턴 분석 결과를 기반으로 새 영상을 자동으로 컷 편집합니다.
무음 구간을 제거하고 말하는 구간만 남깁니다.
"""

import json
import subprocess
import sys
import numpy as np
import librosa
from pathlib import Path
from dataclasses import dataclass

ANALYSIS_DIR = Path(__file__).parent.parent / "analysis"
PATTERN_FILE = ANALYSIS_DIR / "pattern_analysis.json"
OUTPUT_DIR = Path(__file__).parent.parent / "output"


@dataclass
class EditSegment:
    start: float
    end: float
    type: str  # 'keep' or 'cut'


def load_channel_patterns() -> dict:
    if not PATTERN_FILE.exists():
        print("패턴 파일 없음. 먼저 03_analyze_patterns.py를 실행하세요.")
        sys.exit(1)

    with open(PATTERN_FILE, encoding="utf-8") as f:
        data = json.load(f)

    return data.get("channel_patterns", {})


def extract_audio_for_analysis(video_path: Path) -> Path:
    audio_path = video_path.with_suffix("_analysis.wav")
    if audio_path.exists():
        return audio_path

    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    if result.returncode != 0:
        raise RuntimeError(f"오디오 추출 실패: {result.stderr.decode()[:200]}")

    return audio_path


def detect_keep_segments(y: np.ndarray, sr: int,
                          cut_threshold: float,
                          min_silence_db: float = -40.0,
                          padding: float = 0.05) -> list[EditSegment]:
    """
    무음 구간을 감지하고, 유지할 구간(keep) 목록을 반환합니다.
    padding: 말 시작/끝에 약간의 여유를 줌
    """
    frame_length = 2048
    hop_length = 512

    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
    rms_db = librosa.amplitude_to_db(rms, ref=np.max(rms) if rms.max() > 0 else 1.0)
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)

    # 임계값 자동 결정
    avg_db = float(np.mean(rms_db))
    silence_threshold = max(avg_db - 20, min_silence_db)

    is_speech = rms_db >= silence_threshold
    total_duration = len(y) / sr

    # 말하기 구간 추출
    speech_starts = []
    speech_ends = []
    in_speech = False
    seg_start = 0.0

    for t, sp in zip(times, is_speech):
        if sp and not in_speech:
            in_speech = True
            seg_start = t
        elif not sp and in_speech:
            in_speech = False
            speech_starts.append(seg_start)
            speech_ends.append(t)

    if in_speech:
        speech_starts.append(seg_start)
        speech_ends.append(total_duration)

    if not speech_starts:
        return [EditSegment(0.0, total_duration, "keep")]

    # 인접한 말하기 구간 병합 (사이 무음이 cut_threshold 미만이면 병합)
    merged_starts = [speech_starts[0]]
    merged_ends = [speech_ends[0]]

    for s, e in zip(speech_starts[1:], speech_ends[1:]):
        gap = s - merged_ends[-1]
        if gap < cut_threshold:
            merged_ends[-1] = e  # 병합
        else:
            merged_starts.append(s)
            merged_ends.append(e)

    # padding 적용 및 클램핑
    segments = []
    for s, e in zip(merged_starts, merged_ends):
        s_padded = max(0.0, s - padding)
        e_padded = min(total_duration, e + padding)
        segments.append(EditSegment(
            start=round(s_padded, 3),
            end=round(e_padded, 3),
            type="keep",
        ))

    return segments


def build_ffmpeg_filter(segments: list[EditSegment], total_duration: float) -> tuple[str, float]:
    """
    ffmpeg concat filter_complex 문자열 생성
    반환: (filter_complex_str, output_duration)
    """
    parts = []
    total_keep = 0.0

    for i, seg in enumerate(segments):
        dur = seg.end - seg.start
        total_keep += dur
        parts.append(
            f"[0:v]trim=start={seg.start}:end={seg.end},setpts=PTS-STARTPTS[v{i}];"
            f"[0:a]atrim=start={seg.start}:end={seg.end},asetpts=PTS-STARTPTS[a{i}]"
        )

    n = len(segments)
    v_inputs = "".join(f"[v{i}]" for i in range(n))
    a_inputs = "".join(f"[a{i}]" for i in range(n))

    filter_complex = ";".join(parts)
    filter_complex += f";{v_inputs}concat=n={n}:v=1:a=0[outv]"
    filter_complex += f";{a_inputs}concat=n={n}:v=0:a=1[outa]"

    return filter_complex, total_keep


def auto_edit_video(input_path: Path, output_path: Path, patterns: dict,
                    cut_threshold_override: float = None) -> dict:
    """
    영상을 자동 편집합니다.
    """
    cut_threshold = cut_threshold_override or patterns.get("recommended_cut_threshold", 0.5)
    print(f"\n자동 편집: {input_path.name}")
    print(f"  컷 임계값: {cut_threshold:.2f}초 이상 무음 제거")

    # 오디오 분석
    audio_path = extract_audio_for_analysis(input_path)
    y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
    total_duration = len(y) / sr

    print(f"  원본 길이: {total_duration/60:.1f}분")

    # 유지 구간 계산
    segments = detect_keep_segments(y, sr, cut_threshold)
    keep_duration = sum(s.end - s.start for s in segments)
    removed_duration = total_duration - keep_duration

    print(f"  유지 구간: {len(segments)}개, {keep_duration/60:.1f}분")
    print(f"  제거된 무음: {removed_duration/60:.1f}분 ({removed_duration/total_duration*100:.1f}%)")

    if len(segments) == 0:
        print("  경고: 유지할 구간이 없습니다.")
        return {}

    if len(segments) == 1 and segments[0].start == 0 and segments[0].end >= total_duration - 0.1:
        print("  무음 구간 없음, 원본 그대로 복사")
        import shutil
        shutil.copy2(input_path, output_path)
    else:
        # ffmpeg으로 편집
        filter_complex, _ = build_ffmpeg_filter(segments, total_duration)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        cmd = [
            "ffmpeg", "-y", "-i", str(input_path),
            "-filter_complex", filter_complex,
            "-map", "[outv]", "-map", "[outa]",
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "192k",
            str(output_path),
        ]

        print("  ffmpeg 편집 실행 중...")
        result = subprocess.run(cmd, capture_output=True, timeout=600)
        if result.returncode != 0:
            err = result.stderr.decode()[-500:]
            raise RuntimeError(f"ffmpeg 편집 실패:\n{err}")

    # 임시 오디오 파일 정리
    if audio_path.exists() and "_analysis" in audio_path.name:
        audio_path.unlink()

    return {
        "input": str(input_path),
        "output": str(output_path),
        "original_duration": round(total_duration, 2),
        "edited_duration": round(keep_duration, 2),
        "removed_duration": round(removed_duration, 2),
        "reduction_percent": round(removed_duration / total_duration * 100, 1),
        "segment_count": len(segments),
        "cut_threshold": cut_threshold,
    }


def batch_edit(input_dir: Path, output_dir: Path,
               cut_threshold_override: float = None):
    """폴더 내 모든 영상을 배치 처리"""
    patterns = load_channel_patterns()
    video_extensions = {".mp4", ".mov", ".avi", ".mkv", ".m4v", ".webm"}

    videos = [f for f in input_dir.iterdir() if f.suffix.lower() in video_extensions]
    if not videos:
        print(f"영상 파일 없음: {input_dir}")
        return

    print(f"\n배치 편집 시작: {len(videos)}개 영상")
    print(f"입력: {input_dir}")
    print(f"출력: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    for video in sorted(videos):
        out_path = output_dir / f"{video.stem}_edited{video.suffix}"
        try:
            result = auto_edit_video(video, out_path, patterns, cut_threshold_override)
            results.append(result)
            print(f"  완료: {out_path.name} ({result.get('reduction_percent', 0):.1f}% 단축)")
        except Exception as e:
            print(f"  오류: {video.name}: {e}")
            results.append({"input": str(video), "error": str(e)})

    # 결과 저장
    result_file = output_dir / "edit_results.json"
    with open(result_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    success = [r for r in results if "error" not in r]
    print(f"\n=== 배치 편집 완료 ===")
    print(f"성공: {len(success)}/{len(results)}개")
    if success:
        avg_reduction = sum(r["reduction_percent"] for r in success) / len(success)
        print(f"평균 단축률: {avg_reduction:.1f}%")
    print(f"결과 저장: {result_file}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="자동 컷 편집")
    parser.add_argument("input", help="입력 영상 파일 또는 폴더")
    parser.add_argument("--output", "-o", help="출력 경로 (기본: output/)")
    parser.add_argument("--threshold", "-t", type=float,
                        help="무음 컷 임계값(초), 기본: 패턴에서 자동 결정")
    args = parser.parse_args()

    input_path = Path(args.input)
    patterns = load_channel_patterns()

    if input_path.is_dir():
        out_dir = Path(args.output) if args.output else OUTPUT_DIR / input_path.name
        batch_edit(input_path, out_dir, args.threshold)
    elif input_path.is_file():
        out_path = Path(args.output) if args.output else OUTPUT_DIR / f"{input_path.stem}_edited{input_path.suffix}"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = auto_edit_video(input_path, out_path, patterns, args.threshold)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(f"파일 또는 폴더를 찾을 수 없습니다: {input_path}")
        sys.exit(1)
