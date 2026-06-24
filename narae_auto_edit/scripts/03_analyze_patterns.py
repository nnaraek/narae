#!/usr/bin/env python3
"""
Step 3: 편집 패턴 분석
다운로드된 영상의 오디오를 분석해 다음 패턴을 추출합니다:
- 무음 구간 (silence) 위치 및 길이
- 말 속도 (words per minute)
- 컷 타이밍 패턴
- 오디오 에너지 분포
"""

import json
import subprocess
import numpy as np
import librosa
import soundfile as sf
from pathlib import Path
from dataclasses import dataclass, asdict

ANALYSIS_DIR = Path(__file__).parent.parent / "analysis"
DOWNLOAD_DIR = Path(__file__).parent.parent / "downloads"
SAMPLES_FILE = ANALYSIS_DIR / "downloaded_samples.json"


@dataclass
class SilenceSegment:
    start: float
    end: float
    duration: float


@dataclass
class VideoAnalysis:
    video_id: str
    title: str
    duration: float
    path: str

    # 무음 구간
    silence_segments: list
    silence_threshold_db: float
    avg_silence_duration: float
    silence_ratio: float          # 전체 중 무음 비율

    # 말 속도 (Whisper 기반, 나중에 채움)
    estimated_wpm: float

    # 오디오 특성
    avg_rms_db: float             # 평균 음량
    dynamic_range_db: float       # 다이나믹 레인지
    speech_segments: list         # 말하는 구간 목록

    # 컷 추천 포인트
    recommended_cuts: list        # (time, reason) 리스트


def extract_audio(video_path: Path, audio_path: Path) -> bool:
    """영상에서 모노 16kHz WAV 오디오 추출 (Whisper/librosa 최적 형식)"""
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le",
        "-ar", "16000", "-ac", "1",
        str(audio_path),
    ]
    result = subprocess.run(cmd, capture_output=True, timeout=300)
    return result.returncode == 0


def detect_silence(y: np.ndarray, sr: int,
                   min_silence_duration: float = 0.3,
                   silence_threshold_db: float = -40.0) -> list[SilenceSegment]:
    """librosa로 무음 구간 감지"""
    frame_length = 2048
    hop_length = 512

    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
    rms_db = librosa.amplitude_to_db(rms, ref=np.max(rms) if rms.max() > 0 else 1.0)

    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)
    is_silent = rms_db < silence_threshold_db

    segments = []
    in_silence = False
    silence_start = 0.0

    for i, (t, silent) in enumerate(zip(times, is_silent)):
        if silent and not in_silence:
            in_silence = True
            silence_start = t
        elif not silent and in_silence:
            in_silence = False
            duration = t - silence_start
            if duration >= min_silence_duration:
                segments.append(SilenceSegment(
                    start=round(silence_start, 3),
                    end=round(t, 3),
                    duration=round(duration, 3),
                ))

    if in_silence:
        duration = times[-1] - silence_start
        if duration >= min_silence_duration:
            segments.append(SilenceSegment(
                start=round(silence_start, 3),
                end=round(times[-1], 3),
                duration=round(duration, 3),
            ))

    return segments


def detect_speech_segments(y: np.ndarray, sr: int,
                            silence_threshold_db: float = -40.0) -> list[dict]:
    """말하는 구간 목록 생성"""
    frame_length = 2048
    hop_length = 512

    rms = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
    rms_db = librosa.amplitude_to_db(rms, ref=np.max(rms) if rms.max() > 0 else 1.0)
    times = librosa.frames_to_time(np.arange(len(rms)), sr=sr, hop_length=hop_length)

    is_speech = rms_db >= silence_threshold_db
    segments = []
    in_speech = False
    speech_start = 0.0

    for t, sp in zip(times, is_speech):
        if sp and not in_speech:
            in_speech = True
            speech_start = t
        elif not sp and in_speech:
            in_speech = False
            segments.append({"start": round(speech_start, 3), "end": round(t, 3)})

    if in_speech:
        segments.append({"start": round(speech_start, 3), "end": round(times[-1], 3)})

    return segments


def recommend_cuts(silence_segments: list[SilenceSegment],
                   speech_segments: list[dict],
                   total_duration: float) -> list[dict]:
    """
    편집 추천 컷 포인트 생성:
    - 긴 무음 구간의 중간 지점
    - 각 말하기 세션의 시작/끝
    """
    cuts = []

    for seg in silence_segments:
        if seg.duration >= 0.5:
            mid = seg.start + seg.duration / 2
            cuts.append({
                "time": round(mid, 3),
                "reason": f"silence_{seg.duration:.2f}s",
                "silence_start": seg.start,
                "silence_end": seg.end,
                "priority": "high" if seg.duration >= 1.0 else "medium",
            })

    cuts.sort(key=lambda c: c["time"])
    return cuts


def analyze_video(video_info: dict) -> VideoAnalysis | None:
    path = Path(video_info["path"])
    vid = video_info["video"]

    if not path.exists():
        print(f"  파일 없음: {path}")
        return None

    print(f"\n분석 중: {vid['title'][:50]}")
    print(f"  파일: {path.name}")

    # 오디오 추출
    audio_path = ANALYSIS_DIR / f"{vid['id']}_audio.wav"
    if not audio_path.exists():
        print("  오디오 추출 중...")
        if not extract_audio(path, audio_path):
            print("  오디오 추출 실패")
            return None

    # 오디오 로드
    print("  오디오 로드 중...")
    y, sr = librosa.load(str(audio_path), sr=16000, mono=True)
    total_duration = len(y) / sr

    # 적절한 무음 임계값 자동 탐색
    rms = librosa.feature.rms(y=y, frame_length=2048, hop_length=512)[0]
    rms_db = librosa.amplitude_to_db(rms, ref=np.max(rms) if rms.max() > 0 else 1.0)
    avg_rms_db = float(np.mean(rms_db))

    # 임계값 = 평균보다 20dB 낮은 지점 (말이 있는 영상 기준)
    silence_threshold = max(avg_rms_db - 20, -55)

    print(f"  평균 음량: {avg_rms_db:.1f}dB, 무음 임계값: {silence_threshold:.1f}dB")

    # 무음 감지
    print("  무음 구간 감지 중...")
    silence_segs = detect_silence(y, sr, min_silence_duration=0.3,
                                  silence_threshold_db=silence_threshold)

    # 말하기 구간 감지
    speech_segs = detect_speech_segments(y, sr, silence_threshold)

    # 통계
    silence_durations = [s.duration for s in silence_segs]
    avg_silence = float(np.mean(silence_durations)) if silence_durations else 0.0
    total_silence = sum(silence_durations)
    silence_ratio = total_silence / total_duration if total_duration > 0 else 0.0

    # 다이나믹 레인지
    db_values = rms_db[rms_db > -80]
    dynamic_range = float(np.percentile(db_values, 95) - np.percentile(db_values, 5)) if len(db_values) > 0 else 0.0

    # 컷 추천
    cuts = recommend_cuts(silence_segs, speech_segs, total_duration)

    print(f"  무음 구간: {len(silence_segs)}개 (총 {total_silence:.1f}초, {silence_ratio*100:.1f}%)")
    print(f"  말하기 구간: {len(speech_segs)}개")
    print(f"  추천 컷 포인트: {len(cuts)}개")

    return VideoAnalysis(
        video_id=vid["id"],
        title=vid["title"],
        duration=total_duration,
        path=str(path),
        silence_segments=[asdict(s) for s in silence_segs],
        silence_threshold_db=silence_threshold,
        avg_silence_duration=avg_silence,
        silence_ratio=silence_ratio,
        estimated_wpm=0.0,  # Whisper 단계에서 채움
        avg_rms_db=avg_rms_db,
        dynamic_range_db=dynamic_range,
        speech_segments=speech_segs,
        recommended_cuts=cuts,
    )


def aggregate_patterns(analyses: list[VideoAnalysis]) -> dict:
    """여러 영상의 패턴을 집계해 채널 전체의 편집 스타일 도출"""
    if not analyses:
        return {}

    all_silence_durations = []
    for a in analyses:
        all_silence_durations.extend([s["duration"] for s in a.silence_segments])

    return {
        "video_count": len(analyses),
        "avg_silence_ratio": float(np.mean([a.silence_ratio for a in analyses])),
        "avg_silence_duration": float(np.mean(all_silence_durations)) if all_silence_durations else 0,
        "median_silence_duration": float(np.median(all_silence_durations)) if all_silence_durations else 0,
        "p90_silence_duration": float(np.percentile(all_silence_durations, 90)) if all_silence_durations else 0,
        "recommended_cut_threshold": float(np.percentile(all_silence_durations, 60)) if all_silence_durations else 0.5,
        "avg_rms_db": float(np.mean([a.avg_rms_db for a in analyses])),
        "avg_dynamic_range_db": float(np.mean([a.dynamic_range_db for a in analyses])),
        "avg_speech_segments_per_minute": float(np.mean([
            len(a.speech_segments) / (a.duration / 60) for a in analyses if a.duration > 0
        ])),
    }


def main():
    if not SAMPLES_FILE.exists():
        print("샘플 파일 없음. 먼저 02_download_samples.py를 실행하세요.")
        return

    with open(SAMPLES_FILE, encoding="utf-8") as f:
        samples = json.load(f)

    print(f"{len(samples)}개 샘플 영상 분석 시작\n")

    analyses = []
    for sample in samples:
        result = analyze_video(sample)
        if result:
            analyses.append(result)

    # 결과 저장
    analysis_data = [asdict(a) for a in analyses]
    patterns = aggregate_patterns(analyses)

    output = {
        "individual_analyses": analysis_data,
        "channel_patterns": patterns,
    }

    output_file = ANALYSIS_DIR / "pattern_analysis.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n=== 채널 편집 패턴 요약 ===")
    print(f"분석 영상 수: {patterns.get('video_count', 0)}")
    print(f"평균 무음 비율: {patterns.get('avg_silence_ratio', 0)*100:.1f}%")
    print(f"평균 무음 길이: {patterns.get('avg_silence_duration', 0):.2f}초")
    print(f"컷 추천 임계값: {patterns.get('recommended_cut_threshold', 0.5):.2f}초 이상 무음")
    print(f"분당 말하기 세션 수: {patterns.get('avg_speech_segments_per_minute', 0):.1f}개")
    print(f"\n결과 저장: {output_file}")


if __name__ == "__main__":
    main()
