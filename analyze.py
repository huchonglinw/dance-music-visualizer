#!/usr/bin/env python3
"""
analyze.py — 单首歌曲节拍分析脚本
用法:
    python analyze.py "歌曲.mp3"                   → 输出 JSON 到 stdout
    python analyze.py "歌曲.mp3" > beats/歌名.json  → 保存到文件

支持格式: .mp3 .wav .flac .ogg .aac
依赖: pip install librosa numpy
"""
import sys
import os
import json
import numpy as np


def fmt_time(s):
    return f"{int(s//60)}:{int(s%60):02d}"


def analyze(audio_path: str) -> dict:
    try:
        import librosa
    except ImportError:
        print("错误：请先安装 librosa: pip install librosa", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(audio_path):
        print(f"错误：文件不存在: {audio_path}", file=sys.stderr)
        sys.exit(1)

    print(f"📂 加载音频: {os.path.basename(audio_path)}", file=sys.stderr)
    y, sr = librosa.load(audio_path, sr=None, mono=True)
    duration = float(librosa.get_duration(y=y, sr=sr))
    print(f"   时长: {fmt_time(duration)}  采样率: {sr} Hz", file=sys.stderr)

    # ── BPM + 节拍追踪 ──────────────────────────────
    print("🥁 检测 BPM 和节拍...", file=sys.stderr)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, trim=False)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    bpm = float(round(float(np.squeeze(tempo)), 1))
    print(f"   BPM: {bpm}  节拍数: {len(beat_times)}", file=sys.stderr)

    # ── 8拍组起始 ──────────────────────────────────
    bar_starts = [beat_times[i] for i in range(0, len(beat_times), 8)]

    # ── 音乐真正开始时间（onset 检测）────────────────
    print("🎯 检测音乐进入点...", file=sys.stderr)
    onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units='frames',
                                               pre_max=3, post_max=3,
                                               pre_avg=5, post_avg=5,
                                               delta=0.07, wait=10)
    onset_times = librosa.frames_to_time(onset_frames, sr=sr)
    first_onset = float(onset_times[0]) if len(onset_times) > 0 else 0.0

    # 找最近的 beat 作为 music_start
    if beat_times:
        music_start = float(min(beat_times, key=lambda t: abs(t - first_onset)))
    else:
        music_start = first_onset
    print(f"   音乐起点: {music_start:.2f}s", file=sys.stderr)

    # ── 调性检测 ───────────────────────────────────
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    key_idx = int(np.argmax(chroma.mean(axis=1)))
    KEYS = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
    # 简单判断 major/minor：低音能量占比
    low_y = librosa.effects.harmonic(y)
    rms = float(np.mean(librosa.feature.rms(y=low_y)))
    key_mode = "Minor" if rms < 0.05 else "Major"
    key_name = f"{KEYS[key_idx]} {key_mode}"

    # ── 鼓点频率分析 ────────────────────────────────
    print("🔍 分析鼓点层...", file=sys.stderr)
    D = np.abs(librosa.stft(y))
    freqs = librosa.fft_frequencies(sr=sr)

    kick_mask  = freqs < 200
    snare_mask = (freqs >= 200) & (freqs < 3000)
    hihat_mask = freqs >= 3000

    kick_energy  = D[kick_mask, :].mean(axis=0)
    snare_energy = D[snare_mask, :].mean(axis=0)
    hihat_energy = D[hihat_mask, :].mean(axis=0)

    def find_onset_peaks(energy, threshold_ratio=0.6, min_wait=5):
        """从能量包络找峰值时间点"""
        if energy.max() == 0:
            return []
        # 归一化
        norm = energy / energy.max()
        threshold = threshold_ratio
        # 简单峰值检测
        peaks = []
        for i in range(1, len(norm)-1):
            if norm[i] > threshold and norm[i] > norm[i-1] and norm[i] >= norm[i+1]:
                if not peaks or i - peaks[-1] > min_wait:
                    peaks.append(i)
        times = librosa.frames_to_time(np.array(peaks), sr=sr)
        return [round(float(t), 3) for t in times]

    kick_times  = find_onset_peaks(kick_energy,  0.65, min_wait=6)
    snare_times = find_onset_peaks(snare_energy, 0.70, min_wait=8)
    hihat_times = find_onset_peaks(hihat_energy, 0.75, min_wait=3)

    # 过滤掉 music_start 之前的（前奏）
    kick_times  = [t for t in kick_times  if t >= music_start][:300]
    snare_times = [t for t in snare_times if t >= music_start + 2][:300]
    hihat_times = [t for t in hihat_times if t >= music_start + 4][:300]

    print(f"   Kick: {len(kick_times)} 点  Snare: {len(snare_times)} 点  HiHat: {len(hihat_times)} 点", file=sys.stderr)

    # ── 构建事件列表 ────────────────────────────────
    print("📌 生成事件标记...", file=sys.stderr)
    events = []

    # 前奏铺底
    if music_start > 1.0:
        events.append({
            "time": round(first_onset, 3),
            "type": "vinyl",
            "icon": "💿",
            "label": "前奏铺底",
            "desc": "音乐铺底开始，等待主体进入",
            "color": "#888888",
            "is_cue": False
        })

    # 音乐真正开始
    events.append({
        "time": round(music_start, 3),
        "type": "bass",
        "icon": "🔊",
        "label": "音乐进入",
        "desc": "Bass + Kick 同时进来，准备动！",
        "color": "#0a84ff",
        "is_cue": True
    })

    # Snare 进入（取第 4 个 snare 峰值之后）
    if len(snare_times) >= 4:
        snare_entry = snare_times[3]
        events.append({
            "time": round(snare_entry, 3),
            "type": "snare",
            "icon": "🥁",
            "label": "Snare 进入",
            "desc": "小鼓反拍出现，这就是「打 ci」的时机",
            "color": "#ff9f0a",
            "is_cue": True
        })

    # Vocal 进入（分析中段 onset 密度变化）
    mid_onset_frames = librosa.onset.onset_detect(
        y=y[int(sr * music_start):int(sr * (music_start + 30))],
        sr=sr, units='time'
    )
    if len(mid_onset_frames) > 0:
        vocal_start = float(mid_onset_frames[len(mid_onset_frames)//3]) + music_start
        events.append({
            "time": round(vocal_start, 3),
            "type": "vocal",
            "icon": "🎤",
            "label": "人声进入",
            "desc": "Vocal 来了！音乐全开，可以完整跳",
            "color": "#30d158",
            "is_cue": True
        })

    # 段落切换（每 4 个 bar_start = 32拍）
    for i, t in enumerate(bar_starts):
        if i > 0 and i % 4 == 0:
            label_idx = i // 4
            events.append({
                "time": round(t, 3),
                "type": "bar1",
                "icon": "🔁",
                "label": f"第 {label_idx + 1} 大段",
                "desc": f"新段落开始，第 {label_idx + 1} 大段 / 第 {i + 1} 组 8拍",
                "color": "#ff6ec7",
                "is_cue": True
            })

    # 音效突变（全谱能量在 music_start 后的峰值）
    rms_energy = librosa.feature.rms(y=y)[0]
    rms_times  = librosa.frames_to_time(np.arange(len(rms_energy)), sr=sr)
    after_start = rms_times > music_start + 10
    rms_after = rms_energy[after_start]
    if len(rms_after) > 0:
        peak_idx = int(np.argmax(rms_after))
        sfx_time = float(rms_times[after_start][peak_idx])
        events.append({
            "time": round(sfx_time, 3),
            "type": "sfx",
            "icon": "✨",
            "label": "情绪高点",
            "desc": "音乐能量最高点，情绪高峰！",
            "color": "#bf5af2",
            "is_cue": True
        })

    events.sort(key=lambda e: e["time"])

    # ── 歌曲名 / 艺术家（从文件名提取）──────────────
    basename = os.path.basename(audio_path)
    name_no_ext = os.path.splitext(basename)[0]
    if " - " in name_no_ext:
        parts = name_no_ext.split(" - ", 1)
        artist = parts[0].strip()
        song   = parts[1].strip()
    else:
        artist = ""
        song   = name_no_ext

    result = {
        "song":        song,
        "artist":      artist,
        "source_file": basename,
        "bpm":         bpm,
        "key":         key_name,
        "duration":    round(duration, 2),
        "music_start": round(music_start, 3),
        "beats":       [round(t, 3) for t in beat_times],
        "bar_starts":  [round(t, 3) for t in bar_starts],
        "events":      events,
        "drum_events": {
            "kick":  kick_times,
            "snare": snare_times,
            "hihat": hihat_times,
        }
    }
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python analyze.py <音频文件>", file=sys.stderr)
        print("示例: python analyze.py 'Katuchat - Watercolor.mp3' > beats/watercolor.json", file=sys.stderr)
        sys.exit(1)

    data = analyze(sys.argv[1])
    print(json.dumps(data, ensure_ascii=False, indent=2))

    # 成功总结输出到 stderr（不影响 JSON 输出）
    print(f"\n✅ 完成！{data['artist']} - {data['song']}", file=sys.stderr)
    print(f"   BPM: {data['bpm']}  调性: {data['key']}", file=sys.stderr)
    print(f"   时长: {fmt_time(data['duration'])}  节拍: {len(data['beats'])} 拍", file=sys.stderr)
    print(f"   事件标记: {len(data['events'])} 个", file=sys.stderr)
