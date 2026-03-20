# 🕺 Dance Music Visualizer

> 街舞教学音乐分析工具 · AI 分轨 · 节拍可视化 · 8拍卡点训练

**GitHub Pages**: https://huchonglin.github.io/dance-music-visualizer/

---

## 功能

| 功能 | 说明 |
|------|------|
| **AI 分轨** | Demucs v4 分离 Drums / Bass / Vocals / Guitar / Piano |
| **鼓点细分** | Kick / Snare / Hi-Hat 独立波形 + 每拍时间戳标记 |
| **8拍计数器** | 从音乐真实进入点开始计数，Kick=红 / Snare=橙 / Hi-Hat=黄 |
| **进入点检测** | 自动标注 Bass / Vocal / 音效进入时间，提示「该动了」 |
| **变速播放** | 0.5x / 0.75x / 1x，音调保持不变 |
| **Mute / Solo** | 单独听任意音轨 |
| **5套 UI 主题** | Cyberpunk / Neon Tokyo / Dark Forest / Sunset / Clean White |

---

## 项目结构

```
dance-music-visualizer/
├── index.html          # 主页（曲库 + 功能介绍）
├── teacher.html        # 教学分析器主界面（核心功能）
├── themes.html         # 5套主题预览
├── beats/
│   ├── watercolor.json # Katuchat - Watercolor 节拍分析数据
│   └── ...             # 更多歌曲的节拍 JSON
└── songs/
    └── ...             # 预处理好的 stem WAV 文件（可选）
```

---

## beats JSON 格式

由 Python 后端分析后生成，结构如下：

```json
{
  "song": "Watercolor",
  "artist": "Katuchat",
  "bpm": 92,
  "music_start": 4.0,
  "beats": [4.000, 4.652, ...],
  "bar_starts": [4.000, 9.216, ...],
  "events": [
    { "time": 4.0, "type": "bass", "icon": "🔊", "desc": "Bass + Kick 进入" },
    ...
  ]
}
```

---

## 添加新歌曲（本地处理一次）

```bash
# 1. 安装依赖
pip install demucs librosa

# 2. 分轨
demucs -n htdemucs_6s "你的歌曲.mp3"

# 3. 生成节拍 JSON（运行 analyze.py）
python analyze.py "你的歌曲.mp3" > beats/新歌名.json

# 4. 把 beats/*.json 推到 GitHub → 自动生效
```

---

## 本地运行

直接双击 `index.html` 或在浏览器打开即可，无需安装任何依赖。

---

## GitHub Pages 部署

```bash
git clone https://github.com/huchonglin/dance-music-visualizer
cd dance-music-visualizer
# 修改文件后：
git add .
git commit -m "update"
git push
# GitHub Actions 自动部署到 Pages
```

---

## 技术方案

完整技术方案见 [TECH_SOLUTION.md](../docs/TECH_SOLUTION.md)（`Documents/arch-diagram-skill/docs/`）

---

## License

MIT
