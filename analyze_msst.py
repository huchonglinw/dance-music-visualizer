#!/usr/bin/env python3
"""
analyze_msst.py — AI 6轨分离 + 子频段双重分析 (14轨版)

轨道结构 (14轨):
  鼓组 4子轨  : kick / snare / hihat / crash      (drums AI轨 → 频段滤波)
  人声 3子轨  : vocal_lo / vocal_mid / vocal_hi   (vocals AI轨 → 频段滤波)
  贝斯 2子轨  : bass_sub / bass_mid               (bass AI轨 → 频段滤波)
  独立 3轨    : guitar / piano / other
  合成/效果1轨: synth (从 other 高频提取)

使用方法:
  python3 analyze_msst.py <stems_dir> <original_mp3> [--genre lofi/hiphop/default]
  python3 analyze_msst.py separated/6stems songs_audio/watercolor.mp3 --genre lofi

新增 --genre 支持:
  lofi     → 慵懒律动跳法建议
  hiphop   → 弹跳/locking 跳法建议
  default  → 通用跳法建议
"""
import sys, os, json, glob, argparse
import numpy as np


def fmt(s):
    return f"{int(s//60)}:{int(s%60):02d}"


def find_stem_file(stems_dir, stem_name):
    """在 audio-separator / demucs 输出目录中找指定 stem"""
    patterns = [
        os.path.join(stems_dir, f'*({stem_name})*.wav'),
        os.path.join(stems_dir, f'*({stem_name})*.WAV'),
        os.path.join(stems_dir, f'*{stem_name}*.wav'),
        os.path.join(stems_dir, f'{stem_name}.wav'),
        os.path.join(stems_dir, f'{stem_name}.mp3'),
    ]
    for pat in patterns:
        matches = glob.glob(pat, recursive=False)
        if matches:
            return matches[0]
    return None


def band_energy(D, freqs, lo, hi):
    """提取某频段的平均能量时序"""
    mask = (freqs >= lo) & (freqs < hi)
    if not mask.any():
        return None
    return D[mask, :].mean(axis=0)


def detect_hits(norm_energy, thresh=0.45, min_gap=5):
    """局部峰值检测，返回帧索引列表"""
    hits = []
    for i in range(1, len(norm_energy) - 1):
        if (norm_energy[i] > thresh
                and norm_energy[i] > norm_energy[i - 1]
                and norm_energy[i] >= norm_energy[i + 1]):
            if not hits or i - hits[-1] > min_gap:
                hits.append(i)
    return hits


def downsample_curve(norm, dur, pts_per_sec=10):
    """能量曲线下采样到约 10pts/s"""
    ds = max(1, len(norm) // int(dur * pts_per_sec))
    curve = []
    for i in range(0, len(norm), ds):
        c = norm[i:i + ds]
        curve.append(round(float(c.max()), 3))
    return curve


def analyze_band_track(y_stem, sr, n_fft, hop, dur, lo, hi, thresh=0.45, min_gap=5):
    """从 stem 提取指定频段：能量曲线 + hits"""
    import librosa
    D = np.abs(librosa.stft(y_stem, n_fft=n_fft, hop_length=hop))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
    be = band_energy(D, freqs, lo, hi)
    if be is None:
        return {'energy_curve': [], 'onsets': [], 'hits': []}
    bmax = be.max()
    if bmax == 0:
        return {'energy_curve': [], 'onsets': [], 'hits': []}
    bnorm = be / bmax
    hit_frames = detect_hits(bnorm, thresh, min_gap)
    hit_times = librosa.frames_to_time(np.array(hit_frames), sr=sr, hop_length=hop).tolist() if hit_frames else []
    hit_times = [round(float(t), 3) for t in hit_times if t < dur]
    # onset from filtered signal
    band_D = D[(freqs >= lo) & (freqs < hi), :]
    y_band = librosa.istft(band_D, hop_length=hop)
    onsets = librosa.onset.onset_detect(y=y_band, sr=sr, units='time',
                                        pre_max=3, post_max=3,
                                        pre_avg=5, post_avg=5,
                                        delta=0.05, wait=8)
    onsets = [round(float(t), 3) for t in onsets if t < dur]
    return {
        'energy_curve': downsample_curve(bnorm, dur),
        'onsets': onsets,
        'hits': hit_times,
    }


def analyze_full_track(y_stem, sr, n_fft, hop, dur):
    """全频段分析：能量曲线 + hits（用于 guitar/piano/other）"""
    import librosa
    D = np.abs(librosa.stft(y_stem, n_fft=n_fft, hop_length=hop))
    total = D.mean(axis=0)
    tmax = total.max()
    tnorm = total / tmax if tmax > 0 else np.zeros_like(total)
    hit_frames = detect_hits(tnorm, thresh=0.45, min_gap=5)
    hit_times = librosa.frames_to_time(np.array(hit_frames), sr=sr, hop_length=hop).tolist() if hit_frames else []
    hit_times = [round(float(t), 3) for t in hit_times if t < dur]
    onsets = librosa.onset.onset_detect(y=y_stem, sr=sr, units='time',
                                        pre_max=3, post_max=3,
                                        pre_avg=5, post_avg=5,
                                        delta=0.05, wait=8)
    onsets = [round(float(t), 3) for t in onsets if t < dur]
    return {
        'energy_curve': downsample_curve(tnorm, dur),
        'onsets': onsets,
        'hits': hit_times,
    }


# ══════════════════════════════════════════════════════════════
# 14轨配置（实际13→14轨：cymbals 拆 hihat+crash）
#   type='band'  → 从 stem 做频段滤波
#   type='full'  → 直接全频段
# ══════════════════════════════════════════════════════════════
TRACKS_CONFIG = [
    # ── 鼓组 4 子轨（kick/snare/hihat/crash 频段完全不重叠）──
    {'name': 'kick',      'stem': 'drums',  'type': 'band',
     'lo': 30,   'hi': 200,   'thresh': 0.50, 'min_gap': 5,
     'label': 'Kick 底鼓',     'icon': '🥁', 'color': '#ff3b30', 'freq': '30-200Hz'},
    {'name': 'snare',     'stem': 'drums',  'type': 'band',
     'lo': 200,  'hi': 3000,  'thresh': 0.50, 'min_gap': 6,
     'label': 'Snare 军鼓',    'icon': '💥', 'color': '#ff9f0a', 'freq': '200-3kHz'},
    # cymbals 拆分：hihat 短促金属声(3k-8k) vs crash/ride 持续亮镲(8k-18k)
    {'name': 'hihat',     'stem': 'drums',  'type': 'band',
     'lo': 3000, 'hi': 8000,  'thresh': 0.35, 'min_gap': 2,
     'label': 'Hi-Hat 踩镲',   'icon': '🔔', 'color': '#ffd60a', 'freq': '3k-8kHz'},
    {'name': 'crash',     'stem': 'drums',  'type': 'band',
     'lo': 8000, 'hi': 18000, 'thresh': 0.38, 'min_gap': 4,
     'label': 'Crash 亮镲',    'icon': '💥', 'color': '#ffe066', 'freq': '8k-18kHz'},

    # ── 人声 3 子轨（同 stem 内无重叠：80-500 / 500-2k / 2k-8k）──
    {'name': 'vocal_lo',  'stem': 'vocals', 'type': 'band',
     'lo': 80,   'hi': 500,   'thresh': 0.42, 'min_gap': 6,
     'label': 'Vocal 低频',    'icon': '🎤', 'color': '#1ed760', 'freq': '80-500Hz'},
    {'name': 'vocal_mid', 'stem': 'vocals', 'type': 'band',
     'lo': 500,  'hi': 2000,  'thresh': 0.45, 'min_gap': 5,
     'label': 'Vocal 中频',    'icon': '🎙', 'color': '#30d158', 'freq': '500-2kHz'},
    {'name': 'vocal_hi',  'stem': 'vocals', 'type': 'band',
     'lo': 2000, 'hi': 8000,  'thresh': 0.40, 'min_gap': 4,
     'label': 'Vocal 高频',    'icon': '🗣', 'color': '#5ade83', 'freq': '2k-8kHz'},

    # ── 贝斯 2 子轨（同 stem 内无重叠：20-120 / 120-600）──
    {'name': 'bass_sub',  'stem': 'bass',   'type': 'band',
     'lo': 20,   'hi': 120,   'thresh': 0.50, 'min_gap': 5,
     'label': 'Bass Sub 超低频', 'icon': '🔈', 'color': '#0040ff', 'freq': '20-120Hz'},
    {'name': 'bass_mid',  'stem': 'bass',   'type': 'band',
     'lo': 120,  'hi': 600,   'thresh': 0.45, 'min_gap': 5,
     'label': 'Bass Mid 中低频', 'icon': '🎸', 'color': '#0a84ff', 'freq': '120-600Hz'},

    # ── 独立乐器轨（AI 分离后全频段）──
    {'name': 'guitar',    'stem': 'guitar', 'type': 'full',
     'label': 'Guitar 吉他',   'icon': '🎸', 'color': '#ff6b35', 'freq': 'AI全频'},
    {'name': 'piano',     'stem': 'piano',  'type': 'full',
     'label': 'Piano 钢琴',    'icon': '🎹', 'color': '#bf5af2', 'freq': 'AI全频'},

    # ── Other 拆分（同 stem 内无重叠：200-4k / 4k-20k / 全频段独立检测）──
    {'name': 'synth',     'stem': 'other',  'type': 'band',
     'lo': 200,  'hi': 4000,  'thresh': 0.42, 'min_gap': 5,
     'label': 'Synth 合成器',  'icon': '🌊', 'color': '#a78bfa', 'freq': '200-4kHz'},
    {'name': 'fx',        'stem': 'other',  'type': 'band',
     'lo': 4000, 'hi': 20000, 'thresh': 0.35, 'min_gap': 4,
     'label': 'FX/Effects',    'icon': '✨', 'color': '#ff6ec7', 'freq': '4k-20kHz'},
    {'name': 'other',     'stem': 'other',  'type': 'full',
     'label': 'Other 整体',    'icon': '💫', 'color': '#c084fc', 'freq': 'AI全频'},
]


def analyze_6stems(stems_dir, original_mp3):
    import librosa

    print(f"\n📂 6-stem 分析: {stems_dir}", file=sys.stderr)

    # ── 加载原始音频 ──
    print("🎵 加载原始音频...", file=sys.stderr)
    y_orig, sr = librosa.load(original_mp3, sr=None, mono=True)
    dur = float(librosa.get_duration(y=y_orig, sr=sr))

    # BPM + 节拍
    tempo, beat_frames = librosa.beat.beat_track(y=y_orig, sr=sr, trim=False)
    beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    bpm = float(round(float(np.squeeze(tempo)), 1))
    bar_starts = [beat_times[i] for i in range(0, len(beat_times), 8)]

    # 调性
    chroma = librosa.feature.chroma_cqt(y=y_orig, sr=sr)
    key_idx = int(np.argmax(chroma.mean(axis=1)))
    KEYS = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
    key_name = f"{KEYS[key_idx]} Major"

    music_start = float(min(beat_times)) if beat_times else 0.0
    print(f"   BPM={bpm}  调性={key_name}  时长={fmt(dur)}  节拍={len(beat_times)}", file=sys.stderr)

    n_fft = 4096
    hop = 512

    # ── 加载 6 轨 ──
    STEM_NAMES = ['Drums', 'Bass', 'Guitar', 'Piano', 'Vocals', 'Other']
    stem_data = {}
    for sn in STEM_NAMES:
        fpath = find_stem_file(stems_dir, sn)
        if fpath:
            print(f"   ✅ [{sn}]: {os.path.basename(fpath)}", file=sys.stderr)
            y_s, _ = librosa.load(fpath, sr=sr, mono=True)
            stem_data[sn.lower()] = y_s
        else:
            print(f"   ⚠️  缺少 [{sn}]", file=sys.stderr)

    # ── 14轨分析 ──
    stems_result = {}
    tracks_out = []

    for tc in TRACKS_CONFIG:
        name = tc['name']
        stem = tc['stem']

        if stem not in stem_data:
            print(f"   ⏭  跳过 {name}（缺 {stem}）", file=sys.stderr)
            stems_result[name] = {'energy_curve': [], 'onsets': [], 'hits': []}
            tracks_out.append({
                'stem': stem, 'name': name,
                'label': tc['label'], 'icon': tc['icon'],
                'color': tc['color'], 'freq': tc.get('freq', ''),
            })
            continue

        y_stem = stem_data[stem]
        print(f"   🔬 {tc['icon']} {tc['label']}...", file=sys.stderr)

        if tc['type'] == 'band':
            result = analyze_band_track(
                y_stem, sr, n_fft, hop, dur,
                lo=tc['lo'], hi=tc['hi'],
                thresh=tc.get('thresh', 0.45),
                min_gap=tc.get('min_gap', 5),
            )
        else:
            result = analyze_full_track(y_stem, sr, n_fft, hop, dur)

        stems_result[name] = result
        print(f"      hits={len(result['hits'])} onsets={len(result['onsets'])}", file=sys.stderr)
        tracks_out.append({
            'stem': stem, 'name': name,
            'label': tc['label'], 'icon': tc['icon'],
            'color': tc['color'], 'freq': tc.get('freq', ''),
        })

    # ── 事件列表 ──
    events = build_events(stems_result, beat_times, bar_starts, music_start, dur, y_orig, sr)

    # ── 歌名 ──
    bn = os.path.splitext(os.path.basename(original_mp3))[0]
    if ' - ' in bn:
        parts = bn.split(' - ', 1)
        artist, song = parts[0].strip(), parts[1].strip()
    else:
        artist, song = 'Unknown', bn

    # ── 音频文件路径（前端多曲目用）──
    slug = os.path.splitext(os.path.basename(original_mp3))[0].replace(' ', '_').lower()
    audio_files = {
        'main': f'songs_audio/{slug}.mp3',
        'drums':  f'songs_audio/{slug}_stems6/drums.mp3',
        'bass':   f'songs_audio/{slug}_stems6/bass.mp3',
        'guitar': f'songs_audio/{slug}_stems6/guitar.mp3',
        'piano':  f'songs_audio/{slug}_stems6/piano.mp3',
        'vocals': f'songs_audio/{slug}_stems6/vocals.mp3',
        'other':  f'songs_audio/{slug}_stems6/other.mp3',
    }

    # ── 节奏范式分析（rhythm_pattern）──
    rhythm_pattern = analyze_rhythm_pattern(
        stems_result, beat_times, bpm, dur
    )

    return {
        'song': song,
        'artist': artist,
        'source_file': os.path.basename(original_mp3),
        'bpm': bpm,
        'key': key_name,
        'duration': round(dur, 2),
        'music_start': round(music_start, 3),
        # genre 字段：通过 --genre 参数注入，分析后填写
        'genre': {'name': '未分类', 'short': '—', 'type': 'default'},
        'audio_files': audio_files,
        'beats': [round(t, 3) for t in beat_times],
        'bar_starts': [round(t, 3) for t in bar_starts],
        'events': events,
        'rhythm_pattern': rhythm_pattern,
        'separation_model': 'htdemucs_6s (6-stem AI)',
        'tracks_config': tracks_out,
        'stems': stems_result,
    }


def analyze_rhythm_pattern(stems, beat_times, bpm, dur):
    """
    分析节奏范式：kick/snare/cymbals 在 8 beat 中的落点规律。
    返回人类可读的节奏描述 + 数据。
    """
    if not beat_times or len(beat_times) < 8:
        return {'summary': '节拍数据不足', 'details': [], 'kick_pattern': '', 'snare_pattern': ''}

    # 量化每个 hit 到最近的 beat（beat_idx % 8 → 第几拍）
    beat_arr = np.array(beat_times)
    beat_period = 60.0 / bpm if bpm > 0 else 0.5

    def quantize_hits(track_name):
        """返回每个 hit 对应的 beat 位置 (0~7)"""
        hits = stems.get(track_name, {}).get('hits', [])
        if not hits:
            return []
        positions = []
        for h in hits:
            # 找最近 beat
            dists = np.abs(beat_arr - h)
            nearest = np.argmin(dists)
            # 只接受在半拍范围内的
            if dists[nearest] < beat_period * 0.4:
                positions.append(nearest % 8)
        return positions

    kick_pos = quantize_hits('kick')
    snare_pos = quantize_hits('snare')
    hihat_pos = quantize_hits('hihat')
    crash_pos = quantize_hits('crash')
    cymbal_pos = hihat_pos + crash_pos  # 合并用于总体分析

    # 统计每个位置出现频率
    def count_positions(positions):
        counts = [0] * 8
        for p in positions:
            counts[p] += 1
        total = max(1, sum(counts))
        return [round(c / total, 2) for c in counts]

    kick_dist = count_positions(kick_pos)
    snare_dist = count_positions(snare_pos)
    hihat_dist = count_positions(hihat_pos)
    crash_dist = count_positions(crash_pos)
    cymbal_dist = count_positions(cymbal_pos)  # 合并用于总体描述

    # 生成 pattern 字符串（X=强 x=弱 .=无）
    def make_pattern(dist, thresh_strong=0.15, thresh_weak=0.05):
        return ''.join('X' if d >= thresh_strong else ('x' if d >= thresh_weak else '.') for d in dist)

    kick_pat = make_pattern(kick_dist)
    snare_pat = make_pattern(snare_dist)
    hihat_pat = make_pattern(hihat_dist)
    crash_pat = make_pattern(crash_dist)
    cymbal_pat = make_pattern(cymbal_dist)  # 合并用于总体展示

    # 自然语言描述
    details = []
    # Kick 分析
    strong_kicks = [i + 1 for i, d in enumerate(kick_dist) if d >= 0.15]
    if strong_kicks:
        if set(strong_kicks) <= {1, 3, 5, 7}:
            details.append('🥁 底鼓落在重拍（1/3/5/7）— 四四拍驱动')
        elif set(strong_kicks) <= {1, 5}:
            details.append('🥁 底鼓落在1/5拍 — 半拍律动')
        else:
            details.append(f'🥁 底鼓主要在第 {"/".join(map(str, strong_kicks))} 拍')

    # Snare 分析
    strong_snares = [i + 1 for i, d in enumerate(snare_dist) if d >= 0.15]
    if strong_snares:
        if set(strong_snares) <= {2, 4, 6, 8} or set(strong_snares) <= {3, 7}:
            details.append('💥 军鼓落在反拍 — Backbeat 节奏')
        elif set(strong_snares) == {3, 7}:
            details.append('💥 军鼓落在3/7拍 — 标准 Backbeat')
        else:
            details.append(f'💥 军鼓主要在第 {"/".join(map(str, strong_snares))} 拍')

    # Cymbal 分析
    strong_cymbals = [i + 1 for i, d in enumerate(cymbal_dist) if d >= 0.10]
    if len(strong_cymbals) >= 6:
        details.append('🎶 镲片持续 — Hi-Hat 恒定律动')
    elif strong_cymbals:
        details.append(f'🎶 镲片重音在第 {"/".join(map(str, strong_cymbals))} 拍')

    # 综合律动类型判断
    summary = ''
    if kick_pat in ['X.X.X.X.', 'X...X...']:
        if snare_pat in ['..X...X.', '.X..X...', '..X...X.']:
            summary = 'Boom-Bap 律动（底鼓正拍+军鼓反拍）'
        else:
            summary = '正拍驱动律动'
    elif kick_dist[0] >= 0.15 and sum(kick_dist[1:]) > kick_dist[0] * 3:
        summary = '切分底鼓律动（Syncopation）'
    else:
        summary = '自由律动'

    if not details:
        details.append('节奏特征不明显，可能是慵懒/自由律动风格')

    print(f"   🎯 节奏范式: {summary}", file=sys.stderr)
    for d in details:
        print(f"      {d}", file=sys.stderr)

    return {
        'summary': summary,
        'details': details,
        'kick_pattern': kick_pat,
        'snare_pattern': snare_pat,
        'hihat_pattern': hihat_pat,
        'crash_pattern': crash_pat,
        'kick_distribution': kick_dist,
        'snare_distribution': snare_dist,
        'bpm': bpm,
    }


def build_events(stems, beat_times, bar_starts, music_start, dur, y, sr):
    """构建教学事件列表"""
    import librosa
    events = []

    def ev(t, type_, icon, label, desc, color):
        events.append({'time': round(t, 3), 'type': type_, 'icon': icon,
                       'label': label, 'desc': desc, 'color': color, 'is_cue': True})

    ev(music_start, 'start', '🔊', '音乐进入', '音乐开始，准备动！', '#0a84ff')

    # 各轨首次进入
    def first_hit(name, n=0):
        h = stems.get(name, {}).get('hits', [])
        return h[n] if len(h) > n else None

    t = first_hit('kick')
    if t: ev(t, 'kick', '🥁', 'Kick 进入', '底鼓出现！低频冲击感', '#ff3b30')

    t = first_hit('snare', 2)
    if t: ev(t, 'snare', '💥', 'Snare 进入', '军鼓出现！「打ci」的时机', '#ff9f0a')

    t = first_hit('cymbals', 1)
    if t: ev(t, 'cymbals', '🎶', '镲片 进入', '镲片出现，节奏更碎', '#ffd60a')

    t = first_hit('vocal_mid', 1)
    if t: ev(t, 'vocal', '🎤', '人声进入', 'Vocal 出现！', '#30d158')

    t = first_hit('bass_sub', 1)
    if t: ev(t, 'bass_in', '🔈', 'Bass 进入', '低频 Bass 铺底', '#0040ff')

    t = first_hit('guitar', 1)
    if t: ev(t, 'guitar', '🎸', '吉他 进入', 'Guitar 旋律！', '#ff6b35')

    t = first_hit('piano', 1)
    if t: ev(t, 'piano', '🎹', '钢琴 进入', 'Piano 出现！', '#bf5af2')

    t = first_hit('synth', 1)
    if t: ev(t, 'synth', '🌊', 'Synth 进入', '合成器/氛围音色出现', '#a78bfa')

    # 段落切换（每4组8拍）
    for i, t in enumerate(bar_starts):
        if i > 0 and i % 4 == 0:
            ev(round(t, 3), 'bar1', '🔁', f'第{i // 4 + 1}大段',
               f'新段落，第{i + 1}组8拍', '#ff6ec7')

    # 能量高点
    rms = librosa.feature.rms(y=y)[0]
    rms_t = librosa.frames_to_time(np.arange(len(rms)), sr=sr)
    after = rms_t > music_start + 15
    if any(after):
        pi = int(np.argmax(rms[after]))
        ev(round(float(rms_t[after][pi]), 3), 'peak', '🔥', '情绪高点', '全曲能量最高！', '#ff2d55')

    events.sort(key=lambda e: e['time'])
    return events


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='analyze_msst: AI 6-stem → 14轨 JSON')
    parser.add_argument('stems_dir', nargs='?', default='separated/6stems',
                        help='audio-separator 输出目录')
    parser.add_argument('original_mp3', nargs='?', default='songs_audio/watercolor.mp3',
                        help='原始 MP3 文件路径')
    parser.add_argument('--out', default=None,
                        help='输出 JSON 路径（默认 beats/<slug>.json）')
    parser.add_argument('--genre', default='default',
                        choices=['lofi', 'hiphop', 'default'],
                        help='曲风类型 → 前端跳法建议')
    parser.add_argument('--genre-name', default=None,
                        help='曲风完整名称（如 "Lo-Fi Hip Hop"）')
    parser.add_argument('--genre-short', default=None,
                        help='曲风简称（HUD chip 显示，如 "Lo-Fi"）')
    args = parser.parse_args()

    data = analyze_6stems(args.stems_dir, args.original_mp3)

    # 注入曲风
    data['genre'] = {
        'name': args.genre_name or {'lofi': 'Lo-Fi Hip Hop', 'hiphop': 'Hip-Hop'}.get(args.genre, args.genre),
        'short': args.genre_short or {'lofi': 'Lo-Fi', 'hiphop': 'Hip-Hop'}.get(args.genre, args.genre),
        'type': args.genre,
    }

    # 输出路径
    slug = os.path.splitext(os.path.basename(args.original_mp3))[0]
    out_path = args.out or f'beats/{slug}.json'
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"\n✅ 完成: {data['artist']} - {data['song']}", file=sys.stderr)
    print(f"   BPM={data['bpm']}  调性={data['key']}  时长={fmt(data['duration'])}", file=sys.stderr)
    print(f"   轨道数: {len(data['tracks_config'])}", file=sys.stderr)
    for tc in data['tracks_config']:
        n = tc['name']
        h = len(data['stems'].get(n, {}).get('hits', []))
        print(f"   {tc['icon']} {tc['label']:20s} hits={h}", file=sys.stderr)
    print(f"\n   📄 已保存: {out_path}", file=sys.stderr)
    print(f"\n⚡ 提示: 新曲目处理命令模板:", file=sys.stderr)
    print(f"   audio-separator songs/xxx.mp3 --model htdemucs_6s -o separated/", file=sys.stderr)
    print(f"   python3 analyze_msst.py separated/htdemucs_6s/xxx/ songs/xxx.mp3 --genre lofi", file=sys.stderr)
