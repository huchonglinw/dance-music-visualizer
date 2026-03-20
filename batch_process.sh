#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# batch_process.sh
# 街舞音乐教学分析器 - 批量处理脚本
# 功能：NCM解密 → MP3 → 分轨(Demucs) → 节拍分析(librosa) → 生成JSON
#
# 用法：
#   bash batch_process.sh                   # 处理 songs/ 下所有 .ncm/.mp3
#   bash batch_process.sh 一首歌.ncm         # 处理单个文件
#   bash batch_process.sh --skip-demucs     # 只分析节拍，跳过分轨（快速模式）
#
# 依赖（首次运行会自动检查）:
#   pip install ncmdump-py librosa numpy demucs
# ═══════════════════════════════════════════════════════════════

set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SONGS_DIR="$SCRIPT_DIR/songs"
BEATS_DIR="$SCRIPT_DIR/beats"
STEMS_DIR="$SCRIPT_DIR/songs/stems"
CONVERTED_DIR="$SCRIPT_DIR/songs/mp3"

mkdir -p "$BEATS_DIR" "$STEMS_DIR" "$CONVERTED_DIR"

# 颜色输出
RED='\033[0;31m' GREEN='\033[0;32m' YELLOW='\033[1;33m'
BLUE='\033[0;34m' CYAN='\033[0;36m' NC='\033[0m'

log()  { echo -e "${CYAN}[INFO]${NC}  $1"; }
ok()   { echo -e "${GREEN}[✅]${NC}   $1"; }
warn() { echo -e "${YELLOW}[⚠️]${NC}   $1"; }
err()  { echo -e "${RED}[❌]${NC}   $1"; }
section() { echo -e "\n${BLUE}━━━ $1 ━━━${NC}"; }

SKIP_DEMUCS=false
SINGLE_FILE=""

# 参数解析
for arg in "$@"; do
  case "$arg" in
    --skip-demucs) SKIP_DEMUCS=true ;;
    *.ncm|*.mp3|*.wav|*.flac) SINGLE_FILE="$arg" ;;
  esac
done

# ──────────────────────────────────────────────
# 1. 环境检查
# ──────────────────────────────────────────────
section "环境检查"

check_python() {
  if ! command -v python3 &>/dev/null; then
    err "未找到 python3，请先安装 Python 3.9+"
    echo "  macOS: brew install python"
    exit 1
  fi
  ok "Python $(python3 --version | cut -d' ' -f2)"
}

check_dep() {
  local pkg="$1" import_name="${2:-$1}"
  if python3 -c "import $import_name" 2>/dev/null; then
    ok "$pkg 已安装"
  else
    warn "$pkg 未安装，正在安装..."
    pip3 install "$pkg" -q && ok "$pkg 安装成功" || { err "$pkg 安装失败"; exit 1; }
  fi
}

check_python
check_dep "ncmdump-py" "ncmdump"
check_dep "librosa"
check_dep "numpy"

if [ "$SKIP_DEMUCS" = false ]; then
  check_dep "demucs"
fi

# ──────────────────────────────────────────────
# 2. 收集待处理文件
# ──────────────────────────────────────────────
section "收集文件"

declare -a FILES=()

if [ -n "$SINGLE_FILE" ]; then
  if [ -f "$SINGLE_FILE" ]; then
    FILES=("$SINGLE_FILE")
  else
    err "文件不存在: $SINGLE_FILE"
    exit 1
  fi
else
  # 扫描 songs/ 目录下所有支持的格式
  while IFS= read -r -d '' f; do
    FILES+=("$f")
  done < <(find "$SONGS_DIR" -maxdepth 1 \( -name "*.ncm" -o -name "*.mp3" -o -name "*.wav" -o -name "*.flac" \) -print0 2>/dev/null)

  if [ ${#FILES[@]} -eq 0 ]; then
    warn "songs/ 目录下没有找到音频文件"
    echo "  支持格式：.ncm .mp3 .wav .flac"
    echo "  请把音乐文件放入: $SONGS_DIR/"
    exit 0
  fi
fi

log "找到 ${#FILES[@]} 个文件待处理"
for f in "${FILES[@]}"; do
  echo "  📁 $(basename "$f")"
done

# ──────────────────────────────────────────────
# 3. 主处理循环
# ──────────────────────────────────────────────
SUCCESS=0
FAIL=0

for INPUT_FILE in "${FILES[@]}"; do
  BASENAME=$(basename "$INPUT_FILE")
  NAME="${BASENAME%.*}"
  EXT="${BASENAME##*.}"

  section "处理: $BASENAME"

  # ── Step 1: NCM 解密 ──────────────────────────
  MP3_FILE="$INPUT_FILE"

  if [ "$EXT" = "ncm" ]; then
    log "解密 NCM → MP3..."
    MP3_OUTPUT="$CONVERTED_DIR/$NAME.mp3"

    python3 - <<PYEOF
import ncmdump, sys, os
try:
    ncmdump.dump("$INPUT_FILE", "$CONVERTED_DIR")
    print("  NCM 解密成功")
except Exception as e:
    print(f"  NCM 解密失败: {e}")
    sys.exit(1)
PYEOF

    # ncmdump 输出文件名可能带有原始歌曲名，找到它
    MP3_FILE=$(find "$CONVERTED_DIR" -name "*.mp3" -newer "$INPUT_FILE" 2>/dev/null | head -1)
    if [ -z "$MP3_FILE" ]; then
      MP3_FILE="$CONVERTED_DIR/$NAME.mp3"
    fi

    if [ ! -f "$MP3_FILE" ]; then
      err "NCM 解密失败，跳过 $BASENAME"
      FAIL=$((FAIL+1))
      continue
    fi
    ok "解密完成: $(basename "$MP3_FILE")"
  fi

  # ── Step 2: Demucs 分轨 ──────────────────────
  STEM_DIR="$STEMS_DIR/$NAME"

  if [ "$SKIP_DEMUCS" = false ]; then
    log "Demucs 分轨（6轨: Drums/Bass/Vocals/Guitar/Piano/SFX）..."
    log "⏳ 预计耗时 2-5 分钟（取决于歌曲时长）..."

    python3 -m demucs \
      -n htdemucs_6s \
      --out "$STEMS_DIR" \
      "$MP3_FILE" 2>&1 | grep -E "(Separated|error|Exception|%)" || true

    # Demucs 输出目录结构: stems/htdemucs_6s/{song_name}/
    DEMUCS_OUT=$(find "$STEMS_DIR" -type d -name "$NAME" 2>/dev/null | head -1)
    if [ -z "$DEMUCS_OUT" ]; then
      DEMUCS_OUT=$(find "$STEMS_DIR/htdemucs_6s" -maxdepth 1 -type d 2>/dev/null | tail -1)
    fi

    if [ -n "$DEMUCS_OUT" ] && [ -d "$DEMUCS_OUT" ]; then
      ok "分轨完成: $(ls "$DEMUCS_OUT"/*.wav 2>/dev/null | wc -l | tr -d ' ') 轨"
    else
      warn "分轨目录未找到，继续节拍分析"
    fi
  else
    log "跳过分轨（--skip-demucs 模式）"
  fi

  # ── Step 3: 节拍分析 → JSON ──────────────────
  log "分析节拍、调性、事件标记..."
  JSON_OUT="$BEATS_DIR/${NAME}.json"

  python3 "$SCRIPT_DIR/analyze.py" "$MP3_FILE" > "$JSON_OUT" 2>&1

  if [ -f "$JSON_OUT" ] && python3 -c "import json; json.load(open('$JSON_OUT'))" 2>/dev/null; then
    BPM=$(python3 -c "import json; d=json.load(open('$JSON_OUT')); print(d.get('bpm','?'))")
    BEATS_N=$(python3 -c "import json; d=json.load(open('$JSON_OUT')); print(len(d.get('beats',[])))")
    ok "节拍 JSON 生成完成: BPM=$BPM, 共 $BEATS_N 拍"
    ok "输出: beats/${NAME}.json"
    SUCCESS=$((SUCCESS+1))
  else
    err "节拍分析失败: $NAME"
    FAIL=$((FAIL+1))
    continue
  fi
done

# ──────────────────────────────────────────────
# 4. 自动更新曲库 index
# ──────────────────────────────────────────────
section "更新曲库索引"
python3 - <<'PYEOF'
import json, os, glob

beats_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "beats")
songs = []

for jf in sorted(glob.glob(os.path.join(beats_dir, "*.json"))):
    if "index" in os.path.basename(jf):
        continue
    try:
        d = json.load(open(jf))
        songs.append({
            "file": os.path.basename(jf),
            "song":     d.get("song", os.path.basename(jf).replace(".json","")),
            "artist":   d.get("artist", ""),
            "bpm":      d.get("bpm", 0),
            "key":      d.get("key", ""),
            "duration": d.get("duration", 0),
            "music_start": d.get("music_start", 0),
        })
    except Exception as e:
        print(f"  skip {jf}: {e}")

index_path = os.path.join(beats_dir, "index.json")
json.dump({"songs": songs, "count": len(songs)}, open(index_path,"w"), ensure_ascii=False, indent=2)
print(f"  ✅ 曲库索引更新完成，共 {len(songs)} 首歌")
PYEOF

# ──────────────────────────────────────────────
# 5. 自动 git push
# ──────────────────────────────────────────────
section "推送到 GitHub"
cd "$SCRIPT_DIR"

if git rev-parse --git-dir > /dev/null 2>&1; then
  git add beats/ songs/mp3/ 2>/dev/null || true
  CHANGED=$(git status --porcelain | wc -l | tr -d ' ')
  if [ "$CHANGED" -gt 0 ]; then
    git commit -m "🎵 Add beats data: $SUCCESS songs processed"
    git push && ok "已推送到 GitHub，Pages 将在 30 秒内自动更新"
  else
    log "没有新文件需要推送"
  fi
else
  warn "当前目录不是 git 仓库，请手动 push"
fi

# ──────────────────────────────────────────────
# 6. 完成报告
# ──────────────────────────────────────────────
section "完成"
echo ""
echo -e "  ${GREEN}成功${NC}: $SUCCESS 首  ${RED}失败${NC}: $FAIL 首"
echo ""
if [ $SUCCESS -gt 0 ]; then
  echo -e "  🌐 访问: ${CYAN}https://huchonglinw.github.io/dance-music-visualizer/${NC}"
  echo ""
fi
