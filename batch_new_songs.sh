#!/bin/bash
# 批量处理新歌：stem分离 + 分析 + 生成 JSON
set -e
cd "$(dirname "$0")"

SONGS=(
  "MadD3E - G.I. Joe.mp3|hiphop|MadD3E|G.I. Joe|Hip-Hop|🎤|⚡"
  "Shosnny - DJ SHUSTRYI HIP-HOP12.mp3|hiphop|Shosnny|DJ SHUSTRYI HIP-HOP12|Hip-Hop Battle|🏆|🔥"
  "Shosnny - Dj RHAKORZ Track 44.mp3|hiphop|Shosnny|Dj RHAKORZ Track 44|Hip-Hop Battle|🏆|💥"
  "Shosnny - Franky Dee & Ukay Vs Andrey Stylez & Hmel @ Free Spirit.mp3|hiphop|Shosnny|Franky Dee vs Andrey Stylez|Battle HipHop|⚔️|🔥"
  "Shosnny - Juste Debout GENEVA Diablo & Stylezc battle.mp3|hiphop|Shosnny|Juste Debout GENEVA|Battle|⚔️|🥊"
  "Shosnny - Juste Debout2k19 Final Waydi & Rochka vs Diablo & Stylez C.mp3|hiphop|Shosnny|JD2019 Waydi vs Diablo|Battle Final|🏆|👑"
  "Shosnny - KOD2016 中国站 HipHop Final.mp3|hiphop|Shosnny|KOD2016 中国站 HipHop Final|Battle|🇨🇳|🏆"
  "Shosnny - Nvrmind x Boybap - Summertime.mp3|hiphop|Shosnny|Nvrmind x Boybap - Summertime|Hip-Hop|☀️|🌊"
  "Shosnny - Sony Track 28.mp3|hiphop|Shosnny|Sony Track 28|Hip-Hop|🎵|⚡"
  "Shosnny - Sony Track 33.mp3|hiphop|Shosnny|Sony Track 33|Hip-Hop|🎵|🔥"
  "Shosnny - Summer Dance Forever Batalla vs physs(WIN).mp3|hiphop|Shosnny|Summer Dance Forever Battle|Battle|🏖️|🏆"
  "Shosnny - idk the name of the track.mp3|hiphop|Shosnny|idk the name|Hip-Hop|🎶|💫"
  "vortxbeat - LARRY JORDAN BATTLE.mp3|hiphop|vortxbeat|LARRY JORDAN BATTLE|Battle HipHop|🥊|🔥"
  "vortxbeat - LAURENT JORDAN BATTLE.mp3|hiphop|vortxbeat|LAURENT JORDAN BATTLE|Battle HipHop|⚔️|👑"
  "vortxbeat - This Is Hot, What.mp3|hiphop|vortxbeat|This Is Hot What|Hip-Hop|🔥|💥"
)

FAILED=()

for ENTRY in "${SONGS[@]}"; do
  IFS='|' read -r FNAME GENRE ARTIST SONG GENRE_NAME ICON1 ICON2 <<< "$ENTRY"
  MP3="songs/$FNAME"
  
  # 生成 slug（文件名安全化）
  SLUG=$(echo "$FNAME" | sed 's/\.mp3$//' | tr ' ' '_' | tr -cd '[:alnum:]_-' | tr '[:upper:]' '[:lower:]' | cut -c1-40)
  
  STEMS_DIR="separated/${SLUG}_stems"
  BEATS_OUT="beats/${SLUG}.json"
  AUDIO_OUT="songs_audio/${SLUG}.mp3"
  STEMS6_DIR="songs_audio/${SLUG}_stems6"
  
  # 跳过已处理的
  if [ -f "$BEATS_OUT" ]; then
    echo "⏭ 跳过（已有JSON）: $SONG"
    continue
  fi
  
  echo ""
  echo "══════════════════════════════════════════"
  echo "🎵 处理: $SONG"
  echo "══════════════════════════════════════════"
  
  # 1. 复制 MP3 到 songs_audio
  cp "$MP3" "$AUDIO_OUT" && echo "  ✅ MP3 复制完成"
  
  # 2. Stem 分离
  mkdir -p "$STEMS_DIR"
  echo "  🔬 开始 stem 分离（约 1-2 分钟）..."
  audio-separator "$MP3" -m htdemucs_6s.yaml --output_dir "$STEMS_DIR" --output_format wav 2>/dev/null
  if [ $? -ne 0 ]; then
    echo "  ❌ 分离失败：$FNAME"
    FAILED+=("$FNAME")
    continue
  fi
  echo "  ✅ Stem 分离完成"
  
  # 3. 转换 stems 到 MP3
  mkdir -p "$STEMS6_DIR"
  for STEM in Bass Drums Guitar Other Vocals Piano; do
    STEMLOW=$(echo "$STEM" | tr '[:upper:]' '[:lower:]')
    SRC="$STEMS_DIR/$(ls "$STEMS_DIR" | grep -i "($STEM)" | head -1)"
    DST="$STEMS6_DIR/${STEMLOW}.mp3"
    ffmpeg -y -i "$SRC" -b:a 192k "$DST" 2>/dev/null && echo "  ✅ $STEMLOW.mp3" || echo "  ⚠️ $STEMLOW 转换失败"
  done
  
  # 4. 分析 + 生成 JSON
  echo "  📊 分析中..."
  python3 analyze_msst.py "$STEMS_DIR" "$MP3" \
    --genre "$GENRE" \
    --genre-name "$GENRE_NAME" \
    --genre-short "${GENRE_NAME%% *}" \
    --out "$BEATS_OUT" 2>&1 | tail -5
  
  # 5. 修正元数据
  python3 -c "
import json
with open('$BEATS_OUT') as f: d=json.load(f)
d['artist']='$ARTIST'
d['song']='$SONG'
d['icon']='$ICON2'
d['audio_files']={
  'main':'songs_audio/${SLUG}.mp3',
  'drums':'songs_audio/${SLUG}_stems6/drums.mp3',
  'bass':'songs_audio/${SLUG}_stems6/bass.mp3',
  'guitar':'songs_audio/${SLUG}_stems6/guitar.mp3',
  'piano':'songs_audio/${SLUG}_stems6/piano.mp3',
  'vocals':'songs_audio/${SLUG}_stems6/vocals.mp3',
  'other':'songs_audio/${SLUG}_stems6/other.mp3',
}
with open('$BEATS_OUT','w') as f: json.dump(d,f,ensure_ascii=False,indent=2)
print('  ✅ 元数据修正完成')
"

done

echo ""
echo "══════════════════════════════════════════"
echo "✅ 全部处理完成！"
if [ ${#FAILED[@]} -gt 0 ]; then
  echo "❌ 失败的歌曲："
  for F in "${FAILED[@]}"; do echo "   - $F"; done
fi
echo ""
echo "📊 生成的 JSON 文件："
ls beats/*.json
