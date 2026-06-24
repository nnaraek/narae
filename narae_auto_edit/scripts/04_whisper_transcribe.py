#!/usr/bin/env python3
"""
Step 4: Whisper 자막 생성 + 말 속도 분석
다운로드된 영상에 Whisper를 적용해 자막 생성 및 WPM 측정합니다.
"""

import json
import whisper
import re
from pathlib import Path
from dataclasses import dataclass, asdict

ANALYSIS_DIR = Path(__file__).parent.parent / "analysis"
DOWNLOAD_DIR = Path(__file__).parent.parent / "downloads"
SAMPLES_FILE = ANALYSIS_DIR / "downloaded_samples.json"
PATTERN_FILE = ANALYSIS_DIR / "pattern_analysis.json"

# Whisper 모델 크기: tiny/base/small/medium/large
# base = 빠름+적당한 정확도 (한국어는 small 이상 추천)
WHISPER_MODEL = "small"


@dataclass
class Segment:
    start: float
    end: float
    text: str
    word_count: int


def transcribe_audio(audio_path: Path, model) -> list[Segment]:
    print(f"  Whisper 전사 중: {audio_path.name}")
    result = model.transcribe(
        str(audio_path),
        language="ko",
        task="transcribe",
        word_timestamps=False,
        verbose=False,
    )

    segments = []
    for seg in result["segments"]:
        text = seg["text"].strip()
        words = len(re.findall(r'\S+', text))
        segments.append(Segment(
            start=round(seg["start"], 3),
            end=round(seg["end"], 3),
            text=text,
            word_count=words,
        ))

    return segments


def calculate_wpm(segments: list[Segment], total_duration: float) -> float:
    """분당 단어(형태소) 수 계산"""
    total_words = sum(s.word_count for s in segments)
    speech_duration = sum(s.end - s.start for s in segments)
    if speech_duration <= 0:
        return 0.0
    return total_words / (speech_duration / 60)


def segments_to_srt(segments: list[Segment]) -> str:
    """SRT 자막 형식으로 변환"""
    lines = []
    for i, seg in enumerate(segments, 1):
        def fmt_time(t):
            h = int(t // 3600)
            m = int((t % 3600) // 60)
            s = int(t % 60)
            ms = int((t % 1) * 1000)
            return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

        lines.append(str(i))
        lines.append(f"{fmt_time(seg.start)} --> {fmt_time(seg.end)}")
        lines.append(seg.text)
        lines.append("")

    return "\n".join(lines)


def main():
    if not SAMPLES_FILE.exists():
        print("샘플 파일 없음. 먼저 02_download_samples.py를 실행하세요.")
        return

    with open(SAMPLES_FILE, encoding="utf-8") as f:
        samples = json.load(f)

    print(f"Whisper 모델 로드 중: {WHISPER_MODEL}")
    model = whisper.load_model(WHISPER_MODEL)
    print("모델 로드 완료\n")

    transcription_results = []

    for sample in samples:
        vid = sample["video"]
        video_id = vid["id"]
        audio_path = ANALYSIS_DIR / f"{video_id}_audio.wav"

        if not audio_path.exists():
            print(f"오디오 파일 없음 (03_analyze_patterns.py 먼저 실행): {audio_path}")
            continue

        print(f"\n처리 중: {vid['title'][:50]}")
        segments = transcribe_audio(audio_path, model)

        total_duration = vid.get("duration", 0) or 0
        wpm = calculate_wpm(segments, total_duration)
        total_words = sum(s.word_count for s in segments)

        print(f"  세그먼트: {len(segments)}개, 총 단어: {total_words}개, WPM: {wpm:.0f}")

        # SRT 저장
        srt_path = ANALYSIS_DIR / f"{video_id}_subtitles.srt"
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(segments_to_srt(segments))

        transcription_results.append({
            "video_id": video_id,
            "title": vid["title"],
            "wpm": round(wpm, 1),
            "total_words": total_words,
            "segment_count": len(segments),
            "srt_file": str(srt_path),
            "segments": [asdict(s) for s in segments],
        })

    # 패턴 파일에 WPM 데이터 병합
    if PATTERN_FILE.exists():
        with open(PATTERN_FILE, encoding="utf-8") as f:
            pattern_data = json.load(f)

        wpm_values = [r["wpm"] for r in transcription_results if r["wpm"] > 0]
        if wpm_values:
            import numpy as np
            pattern_data["channel_patterns"]["avg_wpm"] = float(round(sum(wpm_values)/len(wpm_values), 1))
            pattern_data["channel_patterns"]["min_wpm"] = float(min(wpm_values))
            pattern_data["channel_patterns"]["max_wpm"] = float(max(wpm_values))

        # 각 영상 분석에 WPM 추가
        for analysis in pattern_data.get("individual_analyses", []):
            for tr in transcription_results:
                if tr["video_id"] == analysis["video_id"]:
                    analysis["estimated_wpm"] = tr["wpm"]
                    break

        with open(PATTERN_FILE, "w", encoding="utf-8") as f:
            json.dump(pattern_data, f, ensure_ascii=False, indent=2)
        print(f"\n패턴 파일에 WPM 데이터 병합 완료")

    # 자막 결과 저장
    output_file = ANALYSIS_DIR / "transcriptions.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(transcription_results, f, ensure_ascii=False, indent=2)

    # 요약 출력
    print(f"\n=== 자막 생성 요약 ===")
    print(f"처리 완료: {len(transcription_results)}개 영상")
    if transcription_results:
        avg_wpm = sum(r["wpm"] for r in transcription_results) / len(transcription_results)
        print(f"평균 말 속도: {avg_wpm:.0f} WPM")
        print("\n영상별 결과:")
        for r in transcription_results:
            print(f"  {r['title'][:40]:40s} | {r['wpm']:5.0f} WPM | {r['segment_count']:3d}개 세그먼트")

    print(f"\n결과 저장: {output_file}")


if __name__ == "__main__":
    main()
