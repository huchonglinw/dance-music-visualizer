#!/usr/bin/env python3
"""
analyze_demucs.py — 基于 Demucs AI 分离后的精细分析
输入: separated/htdemucs/watercolor/ 目录下的 drums.wav, bass.wav, vocals.wav, other.wav
输出: beats/watercolor.json (增强版，含每个真实音轨的独立数据)
"""
import sys, os, json
import numpy as np

def fmt(s):
    return f"{int(s//60)}:{int(s%60):02d}"

def analyze_demucs(stems_dir, original_mp3):
    import librosa
    
    print("📂 分析 Demucs 分离结果:", stems_dir, file=sys.stderr)
    
    # ── 加载原始音频做全局分析 ──
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
    KEYS = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
    key_name = f"{KEYS[key_idx]} Major"
    
    # onset 检测
    onset_frames = librosa.onset.onset_detect(y=y_orig, sr=sr, units='frames')
    onset_times = librosa.frames_to_time(onset_frames, sr=sr)
    music_start = float(min(beat_times)) if beat_times else 0.0
    
    print(f"   BPM={bpm}  调性={key_name}  时长={fmt(dur)}  节拍={len(beat_times)}", file=sys.stderr)
    
    # ── 分析参数 ──
    n_fft = 4096
    hop = 512
    
    # ══════════════════════════════════════════════════════
    # 分析每个分离轨道
    # ══════════════════════════════════════════════════════
    stem_files = {
        'drums':  os.path.join(stems_dir, 'drums.wav'),
        'bass':   os.path.join(stems_dir, 'bass.wav'),
        'vocals': os.path.join(stems_dir, 'vocals.wav'),
        'other':  os.path.join(stems_dir, 'other.wav'),
    }
    
    stems_result = {}
    
    for stem_name, stem_path in stem_files.items():
        if not os.path.exists(stem_path):
            print(f"   ⚠️ 缺少: {stem_path}", file=sys.stderr)
            continue
        
        print(f"\n🔬 分析 [{stem_name}] 轨...", file=sys.stderr)
        y_stem, sr_stem = librosa.load(stem_path, sr=sr, mono=True)
        
        # STFT
        D = np.abs(librosa.stft(y_stem, n_fft=n_fft, hop_length=hop))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=n_fft)
        frame_times = librosa.frames_to_time(np.arange(D.shape[1]), sr=sr, hop_length=hop)
        
        # 全频段能量曲线
        total_energy = D.mean(axis=0)
        te_max = total_energy.max()
        if te_max > 0:
            total_norm = total_energy / te_max
        else:
            total_norm = np.zeros_like(total_energy)
        
        # 下采样（约每 100ms 一个点）
        ds = max(1, len(total_norm) // int(dur * 10))
        energy_curve = []
        for i in range(0, len(total_norm), ds):
            chunk = total_norm[i:i+ds]
            energy_curve.append(round(float(chunk.max()), 3))
        
        # onset 检测（在分离轨道上！更准确）
        onsets = librosa.onset.onset_detect(y=y_stem, sr=sr, units='time',
                                             pre_max=3, post_max=3,
                                             pre_avg=5, post_avg=5,
                                             delta=0.05, wait=8)
        onsets = [round(float(t), 3) for t in onsets if t < dur]
        
        print(f"   全频段 onset: {len(onsets)} 个", file=sys.stderr)
        
        # ── 按子频段细分（每个轨道内部再拆） ──
        sub_bands = get_sub_bands(stem_name)
        sub_results = {}
        
        for sb in sub_bands:
            mask = (freqs >= sb['lo']) & (freqs < sb['hi'])
            if not mask.any():
                sub_results[sb['name']] = {'hits': [], 'energy_curve': []}
                continue
            
            band_e = D[mask, :].mean(axis=0)
            bmax = band_e.max()
            if bmax == 0:
                sub_results[sb['name']] = {'hits': [], 'energy_curve': []}
                continue
            
            bnorm = band_e / bmax
            
            # 峰值检测
            hits = []
            min_gap = sb.get('min_gap', 6)
            thresh = sb.get('thresh', 0.5)
            for i in range(1, len(bnorm)-1):
                if bnorm[i] > thresh and bnorm[i] > bnorm[i-1] and bnorm[i] >= bnorm[i+1]:
                    if not hits or i - hits[-1] > min_gap:
                        hits.append(i)
            
            hit_times = librosa.frames_to_time(np.array(hits), sr=sr, hop_length=hop) if hits else np.array([])
            hit_times = [round(float(t), 3) for t in hit_times if t < dur]
            
            # 下采样
            ds2 = max(1, len(bnorm) // int(dur * 10))
            sub_curve = []
            for i in range(0, len(bnorm), ds2):
                c = bnorm[i:i+ds2]
                sub_curve.append(round(float(c.max()), 3))
            
            sub_results[sb['name']] = {
                'hits': hit_times,
                'energy_curve': sub_curve,
            }
            print(f"   {sb['icon']} {sb['label']}: {len(hit_times)} hits", file=sys.stderr)
        
        stems_result[stem_name] = {
            'energy_curve': energy_curve,
            'onsets': onsets,
            'sub_bands': sub_results,
        }
    
    # ══════════════════════════════════════════════════════
    # 构建事件列表
    # ══════════════════════════════════════════════════════
    events = build_events(stems_result, beat_times, bar_starts, music_start, dur, y_orig, sr)
    
    # ── stems_config（前端用） ──
    all_tracks = []
    for stem_name in ['drums', 'bass', 'vocals', 'other']:
        sbs = get_sub_bands(stem_name)
        for sb in sbs:
            all_tracks.append({
                'stem': stem_name,
                'name': sb['name'],
                'label': sb['label'],
                'icon': sb['icon'],
                'color': sb['color'],
                'freq': f"{sb['lo']}-{sb['hi']}Hz",
            })
    
    # 歌名
    bn = os.path.splitext(os.path.basename(original_mp3))[0]
    if " - " in bn:
        parts = bn.split(" - ", 1)
        artist, song = parts[0].strip(), parts[1].strip()
    else:
        artist, song = "Katuchat", bn
    
    result = {
        'song': song,
        'artist': artist,
        'source_file': os.path.basename(original_mp3),
        'bpm': bpm,
        'key': key_name,
        'duration': round(dur, 2),
        'music_start': round(music_start, 3),
        'beats': [round(t, 3) for t in beat_times],
        'bar_starts': [round(t, 3) for t in bar_starts],
        'events': events,
        'drum_events': {
            'kick': stems_result.get('drums', {}).get('sub_bands', {}).get('kick', {}).get('hits', []),
            'snare': stems_result.get('drums', {}).get('sub_bands', {}).get('snare', {}).get('hits', []),
            'hihat': stems_result.get('drums', {}).get('sub_bands', {}).get('hihat', {}).get('hits', []),
        },
        'tracks_config': all_tracks,
        'stems': stems_result,
    }
    return result


def get_sub_bands(stem_name):
    """每个分离轨道内部的子频段定义"""
    if stem_name == 'drums':
        return [
            {'name':'kick',    'label':'Kick 底鼓',      'icon':'🥁','color':'#ff3b30','lo':30,  'hi':200,  'thresh':0.50,'min_gap':5},
            {'name':'snare',   'label':'Snare 军鼓',     'icon':'💥','color':'#ff9f0a','lo':200, 'hi':1500, 'thresh':0.50,'min_gap':6},
            {'name':'rim',     'label':'Rim/Clap 打击',  'icon':'👏','color':'#ffcc00','lo':1500,'hi':5000, 'thresh':0.45,'min_gap':5},
            {'name':'hihat',   'label':'HiHat 踩镲',     'icon':'🎶','color':'#ffd60a','lo':5000,'hi':16000,'thresh':0.40,'min_gap':3},
        ]
    elif stem_name == 'bass':
        return [
            {'name':'sub_bass','label':'Sub Bass 超低频', 'icon':'🔈','color':'#ff2d55','lo':20,  'hi':80,   'thresh':0.45,'min_gap':8},
            {'name':'bass',    'label':'Bass 贝斯',      'icon':'🎸','color':'#0a84ff','lo':80,  'hi':400,  'thresh':0.45,'min_gap':5},
        ]
    elif stem_name == 'vocals':
        return [
            {'name':'vocal_low', 'label':'Vocal Low 低频人声','icon':'🎤','color':'#30d158','lo':100, 'hi':1000, 'thresh':0.45,'min_gap':4},
            {'name':'vocal_mid', 'label':'Vocal Mid 中频人声','icon':'🗣️','color':'#34c759','lo':1000,'hi':4000, 'thresh':0.40,'min_gap':3},
            {'name':'vocal_hi',  'label':'Vocal Hi 高频人声', 'icon':'✨','color':'#5ac8fa','lo':4000,'hi':12000,'thresh':0.40,'min_gap':3},
        ]
    elif stem_name == 'other':
        return [
            {'name':'synth_low','label':'Synth 合成器低频','icon':'🎹','color':'#bf5af2','lo':60,  'hi':500,  'thresh':0.45,'min_gap':6},
            {'name':'synth_mid','label':'Synth 合成器中频','icon':'🎵','color':'#af52de','lo':500, 'hi':2000, 'thresh':0.40,'min_gap':4},
            {'name':'bell',     'label':'Bell/风铃/叮叮',  'icon':'🔔','color':'#00e5ff','lo':2000,'hi':8000, 'thresh':0.38,'min_gap':3},
            {'name':'fx_hi',    'label':'FX/SFX 高频音效', 'icon':'💫','color':'#ff6ec7','lo':8000,'hi':20000,'thresh':0.35,'min_gap':3},
        ]
    return []


def build_events(stems, beat_times, bar_starts, music_start, dur, y, sr):
    import librosa
    events = []
    
    events.append({'time': round(music_start, 3), 'type':'bass', 'icon':'🔊',
                   'label':'音乐进入', 'desc':'音乐开始，准备动！', 'color':'#0a84ff', 'is_cue':True})
    
    # Kick 第一次出现
    kick_hits = stems.get('drums',{}).get('sub_bands',{}).get('kick',{}).get('hits',[])
    if kick_hits:
        events.append({'time': kick_hits[0], 'type':'kick', 'icon':'🥁',
                       'label':'Kick 进入', 'desc':'底鼓开始！低频冲击感', 'color':'#ff3b30', 'is_cue':True})
    
    # Snare 进入
    snare_hits = stems.get('drums',{}).get('sub_bands',{}).get('snare',{}).get('hits',[])
    if len(snare_hits) >= 3:
        events.append({'time': snare_hits[2], 'type':'snare', 'icon':'💥',
                       'label':'Snare 进入', 'desc':'军鼓出现！「打ci」的时机', 'color':'#ff9f0a', 'is_cue':True})
    
    # HiHat 进入
    hh_hits = stems.get('drums',{}).get('sub_bands',{}).get('hihat',{}).get('hits',[])
    if len(hh_hits) >= 2:
        events.append({'time': hh_hits[1], 'type':'hihat', 'icon':'🎶',
                       'label':'HiHat 进入', 'desc':'踩镲出现，节奏更碎更密', 'color':'#ffd60a', 'is_cue':True})
    
    # Vocal 进入
    vocal_hits = stems.get('vocals',{}).get('sub_bands',{}).get('vocal_mid',{}).get('hits',[])
    if len(vocal_hits) >= 2:
        events.append({'time': vocal_hits[1], 'type':'vocal', 'icon':'🎤',
                       'label':'人声进入', 'desc':'Vocal 出现，听到人声了！', 'color':'#30d158', 'is_cue':True})
    
    # Bell/叮叮 进入
    bell_hits = stems.get('other',{}).get('sub_bands',{}).get('bell',{}).get('hits',[])
    if len(bell_hits) >= 2:
        events.append({'time': bell_hits[1], 'type':'bell', 'icon':'🔔',
                       'label':'风铃/叮叮 进入', 'desc':'高频金属音效！注意这个叮叮声', 'color':'#00e5ff', 'is_cue':True})
    
    # Synth 进入
    synth_hits = stems.get('other',{}).get('sub_bands',{}).get('synth_mid',{}).get('hits',[])
    if len(synth_hits) >= 2:
        events.append({'time': synth_hits[1], 'type':'synth', 'icon':'🎹',
                       'label':'合成器 进入', 'desc':'Synth pad 铺底出现', 'color':'#bf5af2', 'is_cue':True})
    
    # FX 高频
    fx_hits = stems.get('other',{}).get('sub_bands',{}).get('fx_hi',{}).get('hits',[])
    if len(fx_hits) >= 2:
        events.append({'time': fx_hits[1], 'type':'fx', 'icon':'💫',
                       'label':'FX 音效', 'desc':'高频音效出现！', 'color':'#ff6ec7', 'is_cue':True})
    
    # 段落切换
    for i, t in enumerate(bar_starts):
        if i > 0 and i % 4 == 0:
            events.append({'time': round(t,3), 'type':'bar1', 'icon':'🔁',
                           'label': f'第{i//4+1}大段', 'desc': f'新段落开始，第{i+1}组8拍',
                           'color':'#ff6ec7', 'is_cue':True})
    
    # 能量高点
    rms = librosa.feature.rms(y=y)[0]
    rms_t = librosa.frames_to_time(np.arange(len(rms)), sr=sr)
    after = rms_t > music_start + 15
    if any(after):
        pi = int(np.argmax(rms[after]))
        events.append({'time': round(float(rms_t[after][pi]),3), 'type':'peak', 'icon':'🔥',
                       'label':'情绪高点', 'desc':'全曲能量最高！', 'color':'#ff2d55', 'is_cue':True})
    
    events.sort(key=lambda e: e['time'])
    return events


if __name__ == '__main__':
    stems_dir = 'separated/htdemucs/watercolor'
    original_mp3 = 'songs_audio/watercolor.mp3'
    
    if len(sys.argv) >= 3:
        stems_dir = sys.argv[1]
        original_mp3 = sys.argv[2]
    
    data = analyze_demucs(stems_dir, original_mp3)
    print(json.dumps(data, ensure_ascii=False, indent=2))
    
    print(f"\n✅ 分析完成: {data['artist']} - {data['song']}", file=sys.stderr)
    print(f"   BPM={data['bpm']}  调性={data['key']}  时长={fmt(data['duration'])}", file=sys.stderr)
    for tc in data['tracks_config']:
        hits_n = len(data['stems'].get(tc['stem'],{}).get('sub_bands',{}).get(tc['name'],{}).get('hits',[]))
        print(f"   {tc['icon']} {tc['label']} [{tc['stem']}]: {hits_n} hits", file=sys.stderr)
