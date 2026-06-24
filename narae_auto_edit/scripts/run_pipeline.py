#!/usr/bin/env python3
"""
전체 파이프라인 실행기
채널 분석부터 FCPXML 생성까지 한 번에 실행합니다.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).parent
ANALYSIS_DIR = SCRIPTS_DIR.parent / "analysis"
OUTPUT_DIR = SCRIPTS_DIR.parent / "output"


def run_step(script: str, args: list = None):
    cmd = [sys.executable, str(SCRIPTS_DIR / script)]
    if args:
        cmd.extend(args)
    print(f"\n{'='*60}")
    print(f"실행: {script}")
    print('='*60)
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"오류: {script} 실패 (코드 {result.returncode})")
        sys.exit(result.returncode)


def cmd_analyze(args):
    """채널 분석 실행 (01~04 단계)"""
    print("=== 채널 분석 파이프라인 시작 ===")
    run_step("01_fetch_channel.py")
    run_step("02_download_samples.py")
    run_step("03_analyze_patterns.py")
    run_step("04_whisper_transcribe.py")

    pattern_file = ANALYSIS_DIR / "pattern_analysis.json"
    if pattern_file.exists():
        with open(pattern_file, encoding="utf-8") as f:
            data = json.load(f)
        p = data.get("channel_patterns", {})
        print("\n" + "="*60)
        print("채널 편집 패턴 분석 완료!")
        print(f"  무음 제거 임계값: {p.get('recommended_cut_threshold', 0.5):.2f}초")
        print(f"  평균 말 속도: {p.get('avg_wpm', 0):.0f} WPM")
        print(f"  평균 무음 비율: {p.get('avg_silence_ratio', 0)*100:.1f}%")
        print("="*60)


def cmd_edit(args):
    """새 영상 자동 편집 + FCPXML 생성"""
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"경로 없음: {input_path}")
        sys.exit(1)

    output_dir = Path(args.output) if args.output else OUTPUT_DIR / input_path.stem

    edit_args = [str(input_path), "--output", str(output_dir)]
    if args.threshold:
        edit_args += ["--threshold", str(args.threshold)]

    run_step("05_auto_edit.py", edit_args)

    # 편집된 영상에 FCPXML 생성
    video_extensions = {".mp4", ".mov", ".avi", ".mkv", ".m4v"}
    edited_videos = [f for f in output_dir.iterdir()
                     if f.suffix.lower() in video_extensions and "_edited" in f.name]

    for video in edited_videos:
        fcpxml_path = video.with_suffix(".fcpxml")
        run_step("06_generate_fcpxml.py", [str(video), "--output", str(fcpxml_path)])

    print(f"\n편집 완료! 출력 폴더: {output_dir}")
    print("FCPXML 파일을 Final Cut Pro에서 File > Import > XML... 로 열면 됩니다.")


def main():
    parser = argparse.ArgumentParser(description="나래 유튜브 자동 편집 시스템")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # analyze: 채널 분석
    analyze_parser = subparsers.add_parser("analyze", help="채널 영상 분석 (01~04 단계)")

    # edit: 새 영상 편집
    edit_parser = subparsers.add_parser("edit", help="영상 자동 편집 + FCPXML 생성")
    edit_parser.add_argument("input", help="입력 영상 또는 폴더")
    edit_parser.add_argument("--output", "-o", help="출력 폴더")
    edit_parser.add_argument("--threshold", "-t", type=float,
                             help="무음 컷 임계값(초)")

    args = parser.parse_args()

    if args.command == "analyze":
        cmd_analyze(args)
    elif args.command == "edit":
        cmd_edit(args)


if __name__ == "__main__":
    main()
