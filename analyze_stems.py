#!/usr/bin/env python3
"""
analyze_stems.py — 增强版音效分析：按频段拆分成独立 stems 轨道
检测：Sub Bass / Kick / Percussion(敲击) / Snare / Clap / Vocal / Bell(风铃叮叮) / HiHat / Scratch / FX
"""
import sys, os, json
import numpy as np

def fmt(s):
    return f"{int(s//60)}:{int(s%60):02d}"

def analyze_stems(path):
    import librosa
    
    print("📂 加载:", os.path.basename(path), file=sys.stderr)
    y, sr = librosa.load(path, sr=None, mono=True)
    dur = float(librosa.get_duration(y=y, sr=sr))
    print(f"   时长: {fmt(dur)} 采样率: {sr}Hz", file=sys.stderr)
    
    # ── BPM + 节拍 ──
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, trim=False)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    bpm = float(round(float(np.squeeze(tempo)), 1))
    bar_starts = [beat_times[i] for i in range(0, len(beat_times), 8)]
    
    # 调性
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    key_idx = int(np.argmax(chroma.mean(axis=1)))
    KEYS = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
    key_name = f"{KEYS[key_idx]} Major"
    
    # ── STFT 频谱 ──
    print("🔬 STFT 频谱分析...", file=sys.stderr)
    n_fft = 4096
    hop = 512
    D = np.abs(librosa.stft(y, n_fft=n_fft, hop_length=hop))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    frame_times = librosa.frames_to_time(np.arange(D.shape[1]), sr=sr, hop_length=hop)
    
    # ── 频段定义（精细拆分 10 轨） ──
    stems_def = [
        {"name": "sub_bass",   "label": "Sub Bass 超低频",     "lo": 20,    "hi": 60,    "icon": "🔈", "color": "#ff2d55", "threshold": 0.55, "min_wait": 8},
        {"name": "kick",       "label": "Kick 底鼓",           "lo": 60,    "hi": 200,   "icon": "🥁", "color": "#ff3b30", "threshold": 0.60, "min_wait": 6},
        {"name": "percussion", "label": "Percussion 敲击/杯子", "lo": 200,   "hi": 600,   "icon": "🪘", "color": "#ff7700", "threshold": 0.55, "min_wait": 5},
        {"name": "snare",      "label": "Snare 军鼓",          "lo": 600,   "hi": 1200,  "icon": "💥", "color": "#ff9f0a", "threshold": 0.60, "min_wait": 7},
        {"name": "clap",       "label": "Clap/Rim 拍手",       "lo": 1200,  "hi": 2500,  "icon": "👏", "color": "#ffcc00", "threshold": 0.55, "min_wait": 6},
        {"name": "vocal",      "label": "Vocal 人声",          "lo": 2500,  "hi": 5000,  "icon": "🎤", "color": "#30d158", "threshold": 0.50, "min_wait": 4},
        {"name": "vocal_hi",   "label": "Vocal Hi 人声高频",    "lo": 5000,  "hi": 8000,  "icon": "🗣️", "color": "#34c759", "threshold": 0.50, "min_wait": 4},
        {"name": "bell",       "label": "Bell/风铃/叮叮",       "lo": 8000,  "hi": 12000, "icon": "🔔", "color": "#00e5ff", "threshold": 0.45, "min_wait": 3},
        {"name": "hihat",      "label": "HiHat 踩镲",          "lo": 12000, "hi": 16000, "icon": "🎶", "color": "#ffd60a", "threshold": 0.50, "min_wait": 3},
        {"name": "scratch",    "label": "Scratch/FX 音效",      "lo": 16000, "hi": 20000, "icon": "✨", "color": "#bf5af2", "threshold": 0.40, "min_wait": 3},
    ]
    
    stems_data = {}
    
    for sdef in stems_def:
        name = sdef["name"]
        lo_hz, hi_hz = sdef["lo"], sdef["hi"]
        thresh = sdef["threshold"]
        min_w = sdef["min_wait"]
        
        # 提取该频段的能量包络
        mask = (freqs >= lo_hz) & (freqs < hi_hz)
        if not mask.any():
            stems_data[name] = {"hits": [], "energy_curve": []}
            continue
        
        band_energy = D[mask, :].mean(axis=0)
        
        # 归一化
        bmax = band_energy.max()
        if bmax == 0:
            stems_data[name] = {"hits": [], "energy_curve": []}
            continue
        norm = band_energy / bmax
        
        # 峰值检测
        hits = []
        for i in range(1, len(norm)-1):
            if norm[i] > thresh and norm[i] > norm[i-1] and norm[i] >= norm[i+1]:
                if not hits or i - hits[-1] > min_w:
                    hits.append(i)
        
        hit_times = librosa.frames_to_time(np.array(hits), sr=sr, hop_length=hop) if hits else np.array([])
        hit_times = [round(float(t), 3) for t in hit_times if t < dur]
        
        # 下采样能量曲线（约每 100ms 一个点，用于前端绘制）
        downsample = max(1, len(norm) // int(dur * 10))
        energy_curve = []
        for i in range(0, len(norm), downsample):
            chunk = norm[i:i+downsample]
            energy_curve.append(round(float(chunk.max()), 3))
        
        stems_data[name] = {
            "hits": hit_times,
            "energy_curve": energy_curve,
        }
        
        print(f"   {sdef['label']}: {len(hit_times)} 个事件, 能量点 {len(energy_curve)}", file=sys.stderr)
    
    # ── Onset 全谱检测（补充全局音效） ──
    print("🎯 全谱 onset 检测...", file=sys.stderr)
    onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units='frames',
                                               pre_max=3, post_max=3,
                                               pre_avg=5, post_avg=5,
                                               delta=0.07, wait=10)
    onset_times = librosa.frames_to_time(onset_frames, sr=sr)
    music_start = float(min(beat_times, key=lambda t: abs(t - (onset_times[0] if len(onset_times)>0 else 0))))
    
    # ── 谐波/打击分离（用于更精确的人声 vs 鼓点） ──
    print("🎼 Harmonic/Percussive 分离...", file=sys.stderr)
    y_harmonic, y_percussive = librosa.effects.hpss(y)
    
    # 谐波能量曲线（人声/旋律更突出）
    D_harm = np.abs(librosa.stft(y_harmonic, n_fft=n_fft, hop_length=hop))
    harm_vocal_mask = (freqs >= 2000) & (freqs < 8000)
    harm_vocal = D_harm[harm_vocal_mask, :].mean(axis=0)
    hv_max = harm_vocal.max()
    if hv_max > 0:
        harm_vocal_norm = harm_vocal / hv_max
    else:
        harm_vocal_norm = np.zeros_like(harm_vocal)
    
    # 下采样
    ds2 = max(1, len(harm_vocal_norm) // int(dur * 10))
    vocal_harmonic_curve = []
    for i in range(0, len(harm_vocal_norm), ds2):
        chunk = harm_vocal_norm[i:i+ds2]
        vocal_harmonic_curve.append(round(float(chunk.max()), 3))
    
    # 打击能量曲线
    D_perc = np.abs(librosa.stft(y_percussive, n_fft=n_fft, hop_length=hop))
    perc_all = D_perc.mean(axis=0)
    pm = perc_all.max()
    if pm > 0: perc_norm = perc_all / pm
    else: perc_norm = np.zeros_like(perc_all)
    ds3 = max(1, len(perc_norm) // int(dur * 10))
    perc_curve = []
    for i in range(0, len(perc_norm), ds3):
        chunk = perc_norm[i:i+ds3]
        perc_curve.append(round(float(chunk.max()), 3))
    
    # ── 构建事件列表 ──
    events = []
    if music_start > 1.0:
        events.append({"time": round(float(onset_times[0]) if len(onset_times)>0 else 0,3), "type":"vinyl","icon":"💿","label":"前奏铺底","desc":"音乐铺底开始","color":"#888","is_cue":False})
    events.append({"time":round(music_start,3),"type":"bass","icon":"🔊","label":"音乐进入","desc":"Bass+Kick 同时进来，准备动！","color":"#0a84ff","is_cue":True})
    
    # Snare 进入
    snare_hits = stems_data.get("snare",{}).get("hits",[])
    if len(snare_hits)>=4:
        events.append({"time":snare_hits[3],"type":"snare","icon":"🥁","label":"Snare 进入","desc":"小鼓反拍出现，「打 ci」的时机","color":"#ff9f0a","is_cue":True})
    
    # Bell 进入
    bell_hits = stems_data.get("bell",{}).get("hits",[])
    if len(bell_hits)>=2:
        events.append({"time":bell_hits[1],"type":"bell","icon":"🔔","label":"风铃/叮叮 进入","desc":"高频金属音效出现，注意听！","color":"#00e5ff","is_cue":True})
    
    # Vocal 进入
    vocal_hits = stems_data.get("vocal",{}).get("hits",[])
    if len(vocal_hits)>=3:
        events.append({"time":vocal_hits[2],"type":"vocal","icon":"🎤","label":"人声进入","desc":"Vocal 出现，音乐层次更丰富","color":"#30d158","is_cue":True})
    
    # Percussion 进入
    perc_hits = stems_data.get("percussion",{}).get("hits",[])
    if len(perc_hits)>=3:
        events.append({"time":perc_hits[2],"type":"perc","icon":"🪘","label":"敲击声 进入","desc":"敲击/杯子声出现","color":"#ff7700","is_cue":True})
    
    # 段落切换
    for i, t in enumerate(bar_starts):
        if i > 0 and i % 4 == 0:
            li = i // 4
            events.append({"time":round(t,3),"type":"bar1","icon":"🔁","label":f"第{li+1}大段","desc":f"新段落，第{li+1}大段/第{i+1}组8拍","color":"#ff6ec7","is_cue":True})
    
    # 能量高点
    rms_e = librosa.feature.rms(y=y)[0]
    rms_t = librosa.frames_to_time(np.arange(len(rms_e)), sr=sr)
    after = rms_t > music_start + 10
    rms_a = rms_e[after]
    if len(rms_a)>0:
        pi = int(np.argmax(rms_a))
        events.append({"time":round(float(rms_t[after][pi]),3),"type":"sfx","icon":"✨","label":"情绪高点","desc":"音乐能量最高点！","color":"#bf5af2","is_cue":True})
    
    events.sort(key=lambda e: e["time"])
    
    # 歌名
    bn = os.path.splitext(os.path.basename(path))[0]
    if " - " in bn:
        parts = bn.split(" - ", 1)
        artist, song = parts[0].strip(), parts[1].strip()
    else:
        artist, song = "", bn
    
    # ── stems_config（前端用） ──
    stems_config = []
    for s in stems_def:
        stems_config.append({
            "name": s["name"],
            "label": s["label"],
            "icon": s["icon"],
            "color": s["color"],
            "freq": f"{s['lo']}-{s['hi']}Hz",
        })
    
    result = {
        "song": song,
        "artist": artist,
        "source_file": os.path.basename(path),
        "bpm": bpm,
        "key": key_name,
        "duration": round(dur, 2),
        "music_start": round(music_start, 3),
        "beats": [round(t,3) for t in beat_times],
        "bar_starts": [round(t,3) for t in bar_starts],
        "events": events,
        "drum_events": {
            "kick": stems_data.get("kick",{}).get("hits",[]),
            "snare": stems_data.get("snare",{}).get("hits",[]),
            "hihat": stems_data.get("hihat",{}).get("hits",[]),
        },
        "stems_config": stems_config,
        "stems": stems_data,
        "vocal_harmonic_curve": vocal_harmonic_curve,
        "percussion_curve": perc_curve,
    }
    return result

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python analyze_stems.py <音频文件>", file=sys.stderr)
        sys.exit(1)
    data = analyze_stems(sys.argv[1])
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n✅ 分析完成: {data['artist']} - {data['song']}", file=sys.stderr)
    for sc in data["stems_config"]:
        hits_n = len(data["stems"].get(sc["name"],{}).get("hits",[]))
        print(f"   {sc['icon']} {sc['label']}: {hits_n} 个事件", file=sys.stderr)
