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

def run(cmd, **kw):
    return subprocess.run(cmd, shell=True, **kw)

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
                capture_output=True, text=True, cwd=BASE)
        if r.returncode != 0:
            print(f"  ❌ 分离失败: {r.stderr[-200:]}")
            return slug, False
        print(f"  ✅ Stem 分离完成")
    else:
        print(f"  ⏭  Stem 已存在")

    # 3. WAV → MP3
    os.makedirs(stems6, exist_ok=True)
    for stem_label in ["Bass","Drums","Guitar","Other","Piano","Vocals"]:
        dst = os.path.join(stems6, stem_label.lower()+".mp3")
        if os.path.exists(dst): continue
        wavs = glob.glob(os.path.join(stems_dir, f"*({stem_label})*.wav"))
        if not wavs:
            wavs = glob.glob(os.path.join(stems_dir, f"*{stem_label}*.wav"))
        if not wavs:
            print(f"  ⚠️  找不到 {stem_label} WAV")
            continue
        r = run(f'ffmpeg -y -i "{wavs[0]}" -b:a 192k "{dst}"', capture_output=True)
        print(f"  {'✅' if r.returncode==0 else '❌'} {stem_label.lower()}.mp3")

    # 4. 分析
    print(f"  📊 分析 14 轨...")
    r = run(f'python3 analyze_msst.py "{stems_dir}" "{mp3_src}" '
            f'--genre {genre} --genre-name "{genre_name}" --genre-short "{genre_short}" '
            f'--out "{beats_out}"',
            capture_output=True, text=True, cwd=BASE)
    if r.returncode != 0 or not os.path.exists(beats_out):
        print(f"  ❌ 分析失败: {r.stderr[-300:]}")
        return slug, False
    print(r.stdout[-300:] if r.stdout else "  (no stdout)")

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
    ok, fail = [], []
    for entry in SONG_META:
        slug, success = process_song(entry)
        (ok if success else fail).append(entry[1]+" - "+entry[2])
    update_index()
    print(f"\n✅ 成功: {len(ok)}  ❌ 失败: {len(fail)}")
    if fail:
        for f in fail: print(f"  ❌ {f}")
