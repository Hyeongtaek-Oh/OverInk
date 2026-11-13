#!/usr/bin/env bash
# OverInk 설치: 앱 목록(Super 키 검색 / 독 고정)에 등록.
#   ./install.sh              앱 등록
#   ./install.sh --autostart  앱 등록 + 로그인 시 백그라운드 자동 실행
#   ./install.sh --uninstall  등록 해제 (프로젝트 폴더와 설정은 그대로 둠)
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
PY="$DIR/.venv/bin/python"
APPS="$HOME/.local/share/applications"
ICON_DIR="$HOME/.local/share/icons/hicolor/256x256/apps"
AUTOSTART="$HOME/.config/autostart"

refresh() {
    command -v update-desktop-database >/dev/null && update-desktop-database "$APPS" 2>/dev/null || true
    command -v gtk-update-icon-cache >/dev/null && gtk-update-icon-cache -q "$HOME/.local/share/icons/hicolor" 2>/dev/null || true
}

if [[ "${1:-}" == "--uninstall" ]]; then
    rm -f "$APPS/overink.desktop" "$AUTOSTART/overink.desktop" "$ICON_DIR/overink.png"
    refresh
    echo "OverInk 등록을 해제했습니다."
    exit 0
fi

# 파이썬 가상환경 + 의존성
if [[ ! -x "$PY" ]]; then
    python3 -m venv "$DIR/.venv"
fi
"$PY" -m pip install -q -r "$DIR/requirements.txt"

mkdir -p "$APPS" "$ICON_DIR"
"$PY" "$DIR/overink.py" --export-icon "$ICON_DIR/overink.png"

write_entry() {  # $1 = 파일 경로, $2 = 추가 인자
    cat > "$1" <<EOF
[Desktop Entry]
Type=Application
Name=OverInk
GenericName=Screen Annotation
Comment=화면 위에 바로 그리는 발표·화면공유용 주석 도구
Exec="$PY" "$DIR/overink.py" $2
Icon=$ICON_DIR/overink.png
Terminal=false
Categories=Utility;
Keywords=draw;annotate;pen;screen;그리기;주석;펜;화면;
StartupNotify=false
EOF
}

# 앱 아이콘 클릭 = 바로 그리기 모드 (이미 실행 중이면 그 창을 불러냄)
write_entry "$APPS/overink.desktop" "--show"
echo "앱 등록 완료: Super 키 → 'OverInk' 검색 (독에 고정 가능)"

if [[ "${1:-}" == "--autostart" ]]; then
    mkdir -p "$AUTOSTART"
    write_entry "$AUTOSTART/overink.desktop" ""  # 로그인 시엔 숨긴 채 대기
    echo "자동 실행 등록 완료: 로그인하면 백그라운드에서 대기 (Ctrl+Alt+P)"
fi

refresh
