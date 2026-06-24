#!/bin/bash
# Mac에서 narae 자동 편집 시스템 설치 스크립트
set -e

echo "=== narae 자동 편집 시스템 설치 ==="

# Homebrew 확인
if ! command -v brew &>/dev/null; then
    echo "Homebrew가 없습니다. 설치 중..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi

# ffmpeg 설치
if ! command -v ffmpeg &>/dev/null; then
    echo "ffmpeg 설치 중..."
    brew install ffmpeg
else
    echo "ffmpeg 이미 설치됨: $(ffmpeg -version 2>&1 | head -1)"
fi

# Python 확인 (3.10+ 필요)
PYTHON=$(command -v python3.11 || command -v python3.10 || command -v python3)
PYVER=$($PYTHON -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
echo "Python: $PYTHON ($PYVER)"

# pip 패키지 설치
echo "Python 패키지 설치 중..."
$PYTHON -m pip install --upgrade pip
$PYTHON -m pip install yt-dlp openai-whisper librosa numpy scipy pydub soundfile

echo ""
echo "=== 설치 완료 ==="
echo ""
echo "사용법:"
echo "  # 1. 채널 분석 (처음 한 번)"
echo "  python3 scripts/run_pipeline.py analyze"
echo ""
echo "  # 2. 새 영상 자동 편집"
echo "  python3 scripts/run_pipeline.py edit /path/to/your/video.mp4"
echo ""
echo "  # 3. 폴더 전체 배치 처리"
echo "  python3 scripts/run_pipeline.py edit /path/to/video/folder/"
echo ""
echo "출력된 .fcpxml 파일을 Final Cut Pro에서:"
echo "  File > Import > XML... 로 열면 됩니다."
