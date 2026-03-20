#!/usr/bin/env python3
"""批量处理新歌：stem分离 + WAV→MP3 + 分析 + 生成JSON"""
import os, sys, json, re, subprocess, glob, shutil
BASE = os.path.dirname(os.path.abspath(__file__))

SONG_META = [
    # (filename, artist, song, genre_code, genre_name, genre_short, icon)
    ("MadD3E - G.I. Joe.mp3",                         "MadD3E",   "G.I. Joe",                    "hiphop", "Hip-Hop",         "Hip-Hop",  "⚡"),
    ("Shosnny - DJ SHUSTRYI HIP-HOP12.mp3",           "Shosnny",  "DJ SHUSTRYI HIP-HOP12",       "hiphop", "Hip-Hop Battle",  "Battle",   "🔥"),
    ("Shosnny - Dj RHAKORZ Track 44.mp3",             "Shosnny",  "Dj RHAKORZ Track 44",         "hiphop", "Hip-Hop Battle",  "Battle",   "💥"),
    ("Shosnny - Franky Dee & Ukay Vs Andrey Stylez & Hmel @ Free Spirit.mp3",
                                                       "Shosnny",  "Franky Dee vs Andrey Stylez", "hiphop", "Battle HipHop",   "Battle",   "⚔️"),
    ("Shosnny - Juste Debout GENEVA Diablo & Stylezc battle.mp3",
                                                       "Shosnny",  "Juste Debout GENEVA",         "hiphop", "Battle",          "Battle",   "🥊"),
    ("Shosnny - Juste Debout2k19 Final Waydi & Rochka vs Diablo & Stylez C.mp3",
                                                       "Shosnny",  "JD2019 Waydi vs Diablo",      "hiphop", "Battle Final",    "Battle",   "👑"),
    ("Shosnny - KOD2016 中国站 HipHop Final.mp3",     "Shosnny",  "KOD2016 中国站 HipHop Final", "hiphop", "Battle",          "Battle",   "🏆"),
    ("Shosnny - Nvrmind x Boybap - Summertime.mp3",   "Shosnny",  "Nvrmind x Boybap Summertime", "hiphop", "Hip-Hop",         "Hip-Hop",  "☀️"),
    ("Shosnny - Sony Track 28.mp3",                   "Shosnny",  "Sony Track 28",               "hiphop", "Hip-Hop",         "Hip-Hop",  "🎵"),
    ("Shosnny - Sony Track 33.mp3",                   "Shosnny",  "Sony Track 33",               "hiphop", "Hip-Hop",         "Hip-Hop",  "🎶"),
    ("Shosnny - Summer Dance Forever Batalla vs physs(WIN).mp3",
                                                       "Shosnny",  "Summer Dance Forever Battle", "hiphop", "Battle",          "Battle",   "🏖️"),
    ("Shosnny - idk the name of the track.mp3",       "Shosnny",  "idk the name",                "hiphop", "Hip-Hop",         "Hip-Hop",  "🎤"),
    ("vortxbeat - LARRY JORDAN BATTLE.mp3",           "vortxbeat","LARRY JORDAN BATTLE",         "hiphop", "Battle HipHop",   "Battle",   "🥊"),
    ("vortxbeat - LAURENT JORDAN BATTLE.mp3",         "vortxbeat","LAURENT JORDAN BATTLE",       "hiphop", "Battle HipHop",   "Battle",   "⚔️"),
    ("vortxbeat - This Is Hot, What.mp3",             "vortxbeat","This Is Hot What",            "hiphop", "Hip-Hop",         "Hip-Hop",  "🔥"),
]

def slugify(name):
    name = os.path.splitext(name)[0]
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[\s]+', '_', name.strip())
    return name[:40].lower().strip('_')

_DEVNULL = subprocess.DEVNULL  # 线程安全，不使用 open(os.devnull)

def run(cmd, capture=False, **kw):
    """capture=True 仅用于需要读取输出的命令（小输出），默认丢弃 stdout/stderr"""
    if capture:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True, **kw)
    return subprocess.run(cmd, shell=True, stdout=_DEVNULL, stderr=_DEVNULL, **kw)

def process_song(entry):
    fname, artist, song, genre, genre_name, genre_short, icon = entry
    slug = slugify(fname)
    mp3_src  = os.path.join(BASE, "songs", fname)
    stems_dir= os.path.join(BASE, "separated", slug+"_stems")
    audio_out= os.path.join(BASE, "songs_audio", slug+".mp3")
    stems6   = os.path.join(BASE, "songs_audio", slug+"_stems6")
    beats_out= os.path.join(BASE, "beats", slug+".json")

    if os.path.exists(beats_out):
        print(f"⏭  跳过（已有）: {song}")
        return slug, True

    print(f"\n{'='*50}")
    print(f"🎵 {song}  [{slug}]")

    # 1. 复制 MP3
    if not os.path.exists(audio_out):
        shutil.copy2(mp3_src, audio_out)
        print(f"  ✅ MP3 复制")

    # 2. Stem 分离（如果还没有）
    if not os.path.exists(stems_dir) or len(glob.glob(stems_dir+"/*.wav")) < 6:
        os.makedirs(stems_dir, exist_ok=True)
        print(f"  🔬 Stem 分离中...")
        r = run(f'audio-separator "{mp3_src}" -m htdemucs_6s.yaml --output_dir "{stems_dir}" --output_format wav',
                cwd=BASE)
        if r.returncode != 0:
            print(f"  ❌ 分离失败 (code={r.returncode})")
            return slug, False
        print(f"  ✅ Stem 分离完成")
    else:
        print(f"  ⏭  Stem 已存在")

    # 3. WAV → MP3
    os.makedirs(stems6, exist_ok=True)
    for stem_label in ["Bass","Drums","Guitar","Other","Piano","Vocals"]:
        dst = os.path.join(stems6, stem_label.lower()+".mp3")
        if os.path.exists(dst) and os.path.getsize(dst) > 10000: continue
        wavs = glob.glob(os.path.join(stems_dir, f"*({stem_label})*.wav"))
        if not wavs:
            wavs = glob.glob(os.path.join(stems_dir, f"*{stem_label}*.wav"))
        if not wavs:
            print(f"  ⚠️  找不到 {stem_label} WAV")
            continue
        r = run(f'ffmpeg -y -i "{wavs[0]}" -b:a 192k "{dst}"')
        print(f"  {'✅' if r.returncode==0 else '❌'} {stem_label.lower()}.mp3")

    # 4. 分析
    print(f"  📊 分析 14 轨...")
    r = run(f'python3 analyze_msst.py "{stems_dir}" "{mp3_src}" '
            f'--genre {genre} --genre-name "{genre_name}" --genre-short "{genre_short}" '
            f'--out "{beats_out}"',
            capture=True, cwd=BASE)
    if r.returncode != 0 or not os.path.exists(beats_out):
        print(f"  ❌ 分析失败: {r.stderr[-400:]}")
        return slug, False
    if r.stdout: print(r.stdout[-200:])

    # 5. 修正元数据 + audio_files
    with open(beats_out) as f: d = json.load(f)
    d['artist'] = artist
    d['song']   = song
    d['icon']   = icon
    d['audio_files'] = {
        'main':   f'songs_audio/{slug}.mp3',
        'drums':  f'songs_audio/{slug}_stems6/drums.mp3',
        'bass':   f'songs_audio/{slug}_stems6/bass.mp3',
        'guitar': f'songs_audio/{slug}_stems6/guitar.mp3',
        'piano':  f'songs_audio/{slug}_stems6/piano.mp3',
        'vocals': f'songs_audio/{slug}_stems6/vocals.mp3',
        'other':  f'songs_audio/{slug}_stems6/other.mp3',
    }
    with open(beats_out,'w') as f: json.dump(d, f, ensure_ascii=False, indent=2)
    print(f"  ✅ 完成！BPM={d.get('bpm')} 调性={d.get('key')}")
    return slug, True

def update_index():
    beats_dir = os.path.join(BASE, "beats")
    songs = []
    for jf in sorted(glob.glob(beats_dir+"/*.json")):
        if os.path.basename(jf) == "index.json": continue
        with open(jf) as f:
            try: d = json.load(f)
            except: continue
        songs.append({
            "file":        os.path.basename(jf),
            "song":        d.get("song","?"),
            "artist":      d.get("artist","?"),
            "icon":        d.get("icon","🎵"),
            "bpm":         d.get("bpm",0),
            "key":         d.get("key","?"),
            "duration":    d.get("duration",0),
            "music_start": d.get("music_start",0.05),
            "genre_short": d.get("genre",{}).get("short","") if isinstance(d.get("genre"),dict) else "",
        })
    idx = {"songs": songs, "count": len(songs)}
    with open(os.path.join(beats_dir,"index.json"),"w") as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)
    print(f"\n📋 index.json 更新：{len(songs)} 首歌")

if __name__ == "__main__":
    import threading, queue

    # ── 分两阶段并行 ──
    # 阶段1: stem 分离（串行，GPU 单实例）
    # 阶段2: WAV→MP3 + 分析（最多 3 个线程并行）
    MAX_WORKERS = 3

    results = {}
    sep_lock = threading.Lock()  # 保证 stem 分离串行

    def phase1_separate(entry):
        """仅做 stem 分离，跳过已有"""
        fname, artist, song, genre, genre_name, genre_short, icon = entry
        slug = slugify(fname)
        mp3_src   = os.path.join(BASE, "songs", fname)
        stems_dir = os.path.join(BASE, "separated", slug+"_stems")
        audio_out = os.path.join(BASE, "songs_audio", slug+".mp3")
        beats_out = os.path.join(BASE, "beats", slug+".json")
        if os.path.exists(beats_out):
            print(f"⏭  跳过（已有）: {song}")
            results[slug] = True
            return
        if not os.path.exists(audio_out):
            shutil.copy2(mp3_src, audio_out)
        with sep_lock:
            if not os.path.exists(stems_dir) or len(glob.glob(stems_dir+"/*.wav")) < 6:
                os.makedirs(stems_dir, exist_ok=True)
                print(f"🔬 [{song}] Stem 分离中...")
                r = run(f'audio-separator "{mp3_src}" -m htdemucs_6s.yaml --output_dir "{stems_dir}" --output_format wav', cwd=BASE)
                if r.returncode != 0:
                    print(f"❌ [{song}] Stem 分离失败")
                    results[slug] = False
                    return
                print(f"✅ [{song}] Stem 分离完成")
            else:
                print(f"⏭  [{song}] Stem 已存在")

    def phase2_process(entry):
        """WAV→MP3 + 分析 + 元数据（可并行）"""
        fname, artist, song, genre, genre_name, genre_short, icon = entry
        slug = slugify(fname)
        if results.get(slug) is not None:
            return  # 已有结果（成功/失败/跳过）
        mp3_src   = os.path.join(BASE, "songs", fname)
        stems_dir = os.path.join(BASE, "separated", slug+"_stems")
        stems6    = os.path.join(BASE, "songs_audio", slug+"_stems6")
        beats_out = os.path.join(BASE, "beats", slug+".json")
        audio_out = os.path.join(BASE, "songs_audio", slug+".mp3")

        if not os.path.exists(stems_dir) or len(glob.glob(stems_dir+"/*.wav")) < 6:
            results[slug] = False
            return  # stem 分离未完成

        # WAV → MP3（6个 ffmpeg 顺序跑，但多首歌之间并行）
        os.makedirs(stems6, exist_ok=True)
        for stem_label in ["Bass","Drums","Guitar","Other","Piano","Vocals"]:
            dst = os.path.join(stems6, stem_label.lower()+".mp3")
            if os.path.exists(dst) and os.path.getsize(dst) > 10000: continue
            wavs = glob.glob(os.path.join(stems_dir, f"*({stem_label})*.wav"))
            if not wavs: wavs = glob.glob(os.path.join(stems_dir, f"*{stem_label}*.wav"))
            if not wavs: continue
            r = run(f'ffmpeg -y -i "{wavs[0]}" -b:a 192k "{dst}"')
            print(f"  {'✅' if r.returncode==0 else '❌'} [{song}] {stem_label.lower()}.mp3")

        # ── DrumSep：鼓组细拆（drums.wav → kick/snare/toms/hh/cymbals）──
        drums_wav = glob.glob(os.path.join(stems_dir, "*(Drums)*.wav"))
        if not drums_wav:
            drums_wav = glob.glob(os.path.join(stems_dir, "*Drums*.wav"))
        drumsep_dir = os.path.join(stems6, "drumsep")
        # 检查是否已有 DrumSep MP3 输出（最终目标）
        drumsep_mp3_done = all(os.path.exists(os.path.join(stems6, f"{ds}.mp3")) and os.path.getsize(os.path.join(stems6, f"{ds}.mp3")) > 5000 for ds in ["kick","snare","toms","hh","cymbals"])
        if drums_wav and not drumsep_mp3_done:
            os.makedirs(drumsep_dir, exist_ok=True)
            print(f"🥁 [{song}] DrumSep 鼓组细拆中...")
            msst_dir = os.path.join(BASE, "Music-Source-Separation-Training")
            drumsep_cfg = os.path.join(BASE, "models", "drumsep_config.yaml")
            drumsep_ckpt = os.path.join(BASE, "models", "drumsep_5stems_mdx23c_jarredou.ckpt")
            # 创建临时输入目录（MSST inference 需要文件夹）
            tmp_in = os.path.join(BASE, "tmp_drumsep_in")
            os.makedirs(tmp_in, exist_ok=True)
            import shutil as _sh
            _sh.copy2(drums_wav[0], os.path.join(tmp_in, "drums.wav"))
            r = run(f'cd "{msst_dir}" && python3 inference.py '
                    f'--model_type mdx23c '
                    f'--config_path "{drumsep_cfg}" '
                    f'--start_check_point "{drumsep_ckpt}" '
                    f'--input_folder "{tmp_in}" '
                    f'--store_dir "{drumsep_dir}"',
                    cwd=msst_dir)
            _sh.rmtree(tmp_in, ignore_errors=True)
            if r.returncode != 0:
                print(f"⚠️  [{song}] DrumSep 失败（将回退到频率分析）")
            else:
                # MSST 输出到 drumsep_dir/drums/ 子目录（以输入文件名命名）
                # 搜索所有可能的路径
                for ds in ["kick","snare","toms","hh","cymbals"]:
                    wavs = []
                    for search_dir in [drumsep_dir, os.path.join(drumsep_dir, "drums")]:
                        if not os.path.isdir(search_dir):
                            continue
                        wavs = glob.glob(os.path.join(search_dir, f"{ds}.wav"))
                        if not wavs:
                            wavs = glob.glob(os.path.join(search_dir, f"*{ds}*.wav"))
                        if wavs:
                            break
                    if wavs:
                        mp3_dst = os.path.join(stems6, f"{ds}.mp3")
                        run(f'ffmpeg -y -i "{wavs[0]}" -b:a 192k "{mp3_dst}"')
                        print(f"  ✅ {ds}.mp3")
                    else:
                        print(f"  ⚠️  未找到 {ds} WAV 文件")
                print(f"✅ [{song}] DrumSep 完成")
        elif drumsep_mp3_done:
            print(f"⏭  [{song}] DrumSep 已存在")

        # 分析
        print(f"📊 [{song}] 分析 14 轨...")
        r = run(f'python3 analyze_msst.py "{stems_dir}" "{mp3_src}" '
                f'--genre {genre} --genre-name "{genre_name}" --genre-short "{genre_short}" '
                f'--out "{beats_out}"', capture=True, cwd=BASE)
        if r.returncode != 0 or not os.path.exists(beats_out):
            print(f"❌ [{song}] 分析失败: {r.stderr[-300:]}")
            results[slug] = False
            return

        # 元数据
        with open(beats_out) as f: d = json.load(f)
        d.update({'artist':artist,'song':song,'icon':icon,'audio_files':{
            'main':f'songs_audio/{slug}.mp3',
            'drums':f'songs_audio/{slug}_stems6/drums.mp3',
            'bass':f'songs_audio/{slug}_stems6/bass.mp3',
            'guitar':f'songs_audio/{slug}_stems6/guitar.mp3',
            'piano':f'songs_audio/{slug}_stems6/piano.mp3',
            'vocals':f'songs_audio/{slug}_stems6/vocals.mp3',
            'other':f'songs_audio/{slug}_stems6/other.mp3',
            'kick':f'songs_audio/{slug}_stems6/kick.mp3',
            'snare':f'songs_audio/{slug}_stems6/snare.mp3',
            'toms':f'songs_audio/{slug}_stems6/toms.mp3',
            'hh':f'songs_audio/{slug}_stems6/hh.mp3',
            'cymbals':f'songs_audio/{slug}_stems6/cymbals.mp3',
        }})
        with open(beats_out,'w') as f: json.dump(d,f,ensure_ascii=False,indent=2)
        print(f"✅ [{song}] 完成 BPM={d.get('bpm')} 调性={d.get('key')}")
        results[slug] = True

    # 阶段1：串行 stem 分离（跑完所有歌的分离）
    print("=== 阶段1：Stem 分离（串行，避免 GPU OOM）===")
    for entry in SONG_META:
        phase1_separate(entry)

    # 阶段2：并行 WAV→MP3 + 分析
    print(f"\n=== 阶段2：转码+分析（{MAX_WORKERS} 线程并行）===")
    from concurrent.futures import ThreadPoolExecutor, as_completed
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
        futures = {ex.submit(phase2_process, e): e for e in SONG_META}
        for f in as_completed(futures):
            pass  # 进度已在函数内打印

    update_index()
    ok   = [e[2] for e in SONG_META if results.get(slugify(e[0])) is True]
    fail = [e[2] for e in SONG_META if results.get(slugify(e[0])) is False]
    print(f"\n{'='*50}")
    print(f"✅ 成功: {len(ok)}  ❌ 失败: {len(fail)}")
    for f in fail: print(f"  ❌ {f}")
