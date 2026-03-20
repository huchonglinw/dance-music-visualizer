#!/usr/bin/env python3
"""
analyze.py — 将音频文件分析为节拍 JSON 数据
用法: python analyze.py "歌曲.mp3" > beats/歌名.json

依赖: pip install librosa numpy
"""
import sys
import json
import numpy as np

def analyze(audio_path: str) -> dict:
    import librosa

    print(f"加载音频: {audio_path}", file=sys.stderr)
    y, sr = librosa.load(audio_path, sr=None)
    duration = librosa.get_duration(y=y, sr=sr)

    # BPM + 节拍追踪
    print("检测 BPM 和节拍...", file=sys.stderr)
    tempo, beat_frames = librosa.beat.beat_track(y=y, sr=sr, trim=False)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    bpm = float(round(float(tempo), 1))

    # 每 8 拍一组
    bar_starts = [beat_times[i] for i in range(0, len(beat_times), 8)]

    # Onset 检测（用于找"音乐开始"位置）
    print("检测音乐进入点...", file=sys.stderr)
    onset_frames = librosa.onset.onset_detect(y=y, sr=sr, units='frames')
    onset_times = librosa.frames_to_time(onset_frames, sr=sr)

    # 音乐开始时间 = 第一个 onset 附近最近的 beat
    first_onset = float(onset_times[0]) if len(onset_times) > 0 else 0.0
    music_start = min(beat_times, key=lambda t: abs(t - first_onset))

    # 调性检测（简单版）
    chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
    key_idx = int(np.argmax(chroma.mean(axis=1)))
    KEYS = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
    key_name = KEYS[key_idx] + ' Minor'

    # 简单的鼓点分析（频率分层）
    print("分析鼓点...", file=sys.stderr)
    D = np.abs(librosa.stft(y))
    freqs = librosa.fft_frequencies(sr=sr)
    kick_mask  = freqs < 200
    snare_mask = (freqs >= 200) & (freqs < 3000)
    hihat_mask = freqs >= 3000

    kick_energy  = D[kick_mask, :].mean(axis=0)
    snare_energy = D[snare_mask, :].mean(axis=0)
    hihat_energy = D[hihat_mask, :].mean(axis=0)

    # 对能量做归一化
    def norm(arr):
        m = arr.max()
        return (arr / m).tolist() if m > 0 else arr.tolist()

    # 找 Kick/Snare/HiHat 的峰值时间点（用于事件标记）
    def find_peaks(energy, threshold=0.6):
        from librosa.util import peak_pick
        frames = peak_pick(energy, pre_max=3, post_max=3, pre_avg=5, post_avg=5,
                           delta=threshold * energy.max(), wait=5)
        return librosa.frames_to_time(frames, sr=sr).tolist()

    kick_times  = find_peaks(kick_energy, 0.65)
    snare_times = find_peaks(snare_energy, 0.7)
    hihat_times = find_peaks(hihat_energy, 0.75)

    # 人声进入时间（Vocal onset：前 1/4 段落找能量突变）
    vocal_start = None
    mid = len(y) // 4
    vocal_onset = librosa.onset.onset_detect(y=y[mid:], sr=sr, units='time')
    if len(vocal_onset) > 0:
        vocal_start = float(vocal_onset[0]) + duration/4

    # 构建大事件列表
    events = []
    # 音乐开始
    events.append({
        "time": round(float(music_start), 3),
        "type": "bass",
        "icon": "🔊",
        "label": "音乐进入",
        "desc": "Bass + Kick 同时进来，准备动！",
        "color": "#0a84ff",
        "is_cue": True
    })
    # Snare 进入（第一个 snare peak 之后）
    snare_first = snare_times[8] if len(snare_times) > 8 else (float(music_start) + 4)
    events.append({
        "time": round(snare_first, 3),
        "type": "snare",
        "icon": "🥁",
        "label": "Snare 进入",
        "desc": "小鼓反拍出现，这就是「打 ci」的时机",
        "color": "#ff9f0a",
        "is_cue": True
    })
    # 人声进入
    if vocal_start:
        events.append({
            "time": round(vocal_start, 3),
            "type": "vocal",
            "icon": "🎤",
            "label": "人声进入",
            "desc": "Vocal 进来了，音乐全开！",
            "color": "#30d158",
            "is_cue": True
        })
    # 段落切换（每 32 拍）
    for i, t in enumerate(bar_starts):
        if i > 0 and i % 4 == 0:
            events.append({
                "time": round(t, 3),
                "type": "bar1",
                "icon": "🔁",
                "label": f"第 {i//4 + 1} 大段",
                "desc": f"新段落开始，第 {i//4 + 1} 大段",
                "color": "#ff6ec7",
                "is_cue": True
            })

    events.sort(key=lambda e: e["time"])

    result = {
        "song": audio_path.split("/")[-1].rsplit(".",1)[0],
        "artist": "",
        "bpm": bpm,
        "key": key_name,
        "duration": round(duration, 2),
        "music_start": round(float(music_start), 3),
        "beats": [round(t, 3) for t in beat_times],
        "bar_starts": [round(t, 3) for t in bar_starts],
        "events": events,
        "drum_events": {
            "kick":  [round(t, 3) for t in kick_times[:200]],
            "snare": [round(t, 3) for t in snare_times[:200]],
            "hihat": [round(t, 3) for t in hihat_times[:200]],
        }
    }
    return result


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python analyze.py <音频文件路径>", file=sys.stderr)
        print("示例: python analyze.py watercolor.mp3 > beats/watercolor.json", file=sys.stderr)
        sys.exit(1)

    data = analyze(sys.argv[1])
    print(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"\n✅ 分析完成: {data['bpm']} BPM, {len(data['beats'])} 拍, "
          f"音乐起点 {data['music_start']}s", file=sys.stderr)
