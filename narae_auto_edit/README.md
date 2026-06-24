# narae 유튜브 자동 편집 시스템

유튜브 채널 영상을 분석해 자동으로 컷 편집하고 Final Cut Pro용 FCPXML을 생성하는 시스템입니다.

## 전체 흐름

```
채널 분석 (1회)                    새 영상 편집 (매번)
─────────────────                  ──────────────────────
01. 영상 목록 수집  →               05. 무음 구간 자동 제거
02. 샘플 다운로드   →               06. FCPXML 생성
03. 오디오 패턴 분석 →              └→ Final Cut Pro에서 열기
04. Whisper 자막+WPM
```

## 설치 (Mac)

```bash
bash setup_mac.sh
```

## 사용법

### 1단계: 채널 분석 (처음 한 번만)

```bash
python3 scripts/run_pipeline.py analyze
```

`analysis/` 폴더에 다음이 생성됩니다:
- `channel_videos.json` — 전체 영상 목록
- `pattern_analysis.json` — 편집 패턴 (무음 임계값, WPM 등)
- `transcriptions.json` — 샘플 영상 자막
- `*_subtitles.srt` — 각 영상 SRT 자막

### 2단계: 새 영상 자동 편집

```bash
# 단일 영상
python3 scripts/run_pipeline.py edit /path/to/video.mp4

# 폴더 전체 배치
python3 scripts/run_pipeline.py edit /path/to/folder/

# 무음 임계값 직접 지정 (초)
python3 scripts/run_pipeline.py edit video.mp4 --threshold 0.4
```

`output/` 폴더에 다음이 생성됩니다:
- `*_edited.mp4` — 무음 제거된 영상
- `*_edited.fcpxml` — Final Cut Pro 프로젝트 (자막 포함)

### Final Cut Pro에서 열기

`File > Import > XML...` → `.fcpxml` 파일 선택

---

## 스크립트별 설명

| 파일 | 역할 |
|------|------|
| `01_fetch_channel.py` | yt-dlp로 채널 영상 목록 수집 |
| `02_download_samples.py` | 분석용 샘플 영상 다운로드 (5개) |
| `03_analyze_patterns.py` | librosa로 무음/말하기 패턴 분석 |
| `04_whisper_transcribe.py` | Whisper로 자막 생성 + WPM 측정 |
| `05_auto_edit.py` | 패턴 기반 자동 컷 편집 (ffmpeg) |
| `06_generate_fcpxml.py` | FCPXML 1.11 파일 생성 |
| `run_pipeline.py` | 전체 파이프라인 실행기 |

## 분석 항목

- **무음 임계값**: 이보다 긴 무음은 자동으로 제거 (채널 패턴에서 자동 결정)
- **WPM (분당 단어 수)**: 말 속도 측정
- **무음 비율**: 전체 영상 중 무음 구간 비율
- **추천 컷 포인트**: 편집하기 좋은 타이밍 목록

## 요구사항

- Python 3.10+
- ffmpeg (brew install ffmpeg)
- 패키지: yt-dlp, openai-whisper, librosa, numpy, scipy, pydub
