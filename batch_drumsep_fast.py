#!/usr/bin/env python3
"""
batch_drumsep_fast.py — 高速批量 DrumSep + 分析
  Phase 1: DrumSep GPU 推理（串行，GPU 单实例）
  Phase 2: WAV→MP3 转码（8 线程并行）
  Phase 3: 分析 JSON（8 线程并行）
"""
import os, sys, glob, subprocess, shutil, re, json
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

BASE = os.path.dirname(os.path.abspath(__file__))
MSST = os.path.join(BASE, 'Music-Source-Separation-Training')
CFG = os.path.join(BASE, 'models', 'drumsep_config.yaml')
CKPT = os.path.join(BASE, 'models', 'drumsep_5stems_mdx23c_jarredou.ckpt')
STEMS = ['kick', 'snare', 'toms', 'hh', 'cymbals']
TMP = os.path.join(BASE, 'tmp_drumsep_batch')
WORKERS = 8
_lock = threading.Lock()
_DEVNULL = subprocess.DEVNULL

def run(cmd, **kw):
    return subprocess.run(cmd, shell=True, stdout=_DEVNULL, stderr=_DEVNULL, **kw)

def slugify(name):
    name = os.path.splitext(name)[0]
    name = re.sub(r'[^\w\s-]', '', name)
    name = re.sub(r'[\s]+', '_', name.strip())
    return name[:40].lower().strip('_')

# 收集所有歌曲的 drums WAV
def collect_songs():
    songs = []
    for d in sorted(glob.glob(os.path.join(BASE, 'separated', '*_stems'))):
        drums = glob.glob(os.path.join(d, '*(Drums)*.wav'))
        if not drums:
            drums = glob.glob(os.path.join(d, '*Drums*.wav'))
        if not drums:
            continue
        slug = os.path.basename(d).replace('_stems', '')
        stems6 = os.path.join(BASE, 'songs_audio', slug + '_stems6')
        # 检查是否已有 DrumSep MP3
        done = all(
            os.path.exists(os.path.join(stems6, f'{s}.mp3')) and
            os.path.getsize(os.path.join(stems6, f'{s}.mp3')) > 5000
            for s in STEMS
        )
        songs.append({
            'slug': slug,
            'drums_wav': drums[0],
            'stems_dir': d,
            'stems6': stems6,
            'done': done,
        })
    return songs

# ══════════════════════════════════════════════════════════════
# Phase 1: GPU 推理（串行，一次跑一首）
# ══════════════════════════════════════════════════════════════
def phase1_drumsep(songs):
    todo = [s for s in songs if not s['done']]
    if not todo:
        print(f'✅ Phase 1: 所有 {len(songs)} 首歌的 DrumSep 已完成，跳过')
        return

    print(f'\n{"="*60}')
    print(f'Phase 1: DrumSep GPU 推理 ({len(todo)} 首待处理)')
    print(f'{"="*60}')

    # 批量模式：把所有 drums.wav 复制到一个临时目录，一次性推理
    os.makedirs(TMP, exist_ok=True)
    for s in todo:
        # 以 slug 命名避免冲突
        dst = os.path.join(TMP, f'{s["slug"]}_drums.wav')
        if not os.path.exists(dst):
            shutil.copy2(s['drums_wav'], dst)
            print(f'  📋 {s["slug"]}')

    out_dir = os.path.join(BASE, 'tmp_drumsep_batch_out')
    os.makedirs(out_dir, exist_ok=True)

    print(f'\n🥁 启动 DrumSep 批量推理（{len(todo)} 个文件）...')
    r = subprocess.run(
        f'cd "{MSST}" && python3 inference.py '
        f'--model_type mdx23c '
        f'--config_path "{CFG}" '
        f'--start_check_point "{CKPT}" '
        f'--input_folder "{TMP}" '
        f'--store_dir "{out_dir}"',
        shell=True, cwd=MSST
    )

    if r.returncode != 0:
        print('❌ DrumSep 批量推理失败')
        return

    # 整理输出：从 out_dir/{slug}_drums/{stem}.wav → songs_audio/{slug}_stems6/drumsep/
    for s in todo:
        src_subdir = os.path.join(out_dir, f'{s["slug"]}_drums')
        if not os.path.isdir(src_subdir):
            print(f'  ⚠️  {s["slug"]}: 无输出目录')
            continue
        ds_dir = os.path.join(s['stems6'], 'drumsep')
        os.makedirs(ds_dir, exist_ok=True)
        for f in glob.glob(os.path.join(src_subdir, '*.wav')):
            shutil.copy2(f, os.path.join(ds_dir, os.path.basename(f)))
        s['drumsep_dir'] = ds_dir
        print(f'  ✅ {s["slug"]}')

    # 清理临时文件
    shutil.rmtree(TMP, ignore_errors=True)
    shutil.rmtree(out_dir, ignore_errors=True)
    print(f'✅ Phase 1 完成')

# ══════════════════════════════════════════════════════════════
# Phase 2: WAV→MP3 转码（多线程并行）
# ══════════════════════════════════════════════════════════════
def convert_one(song):
    stems6 = song['stems6']
    ds_dir = os.path.join(stems6, 'drumsep')
    count = 0
    for stem in STEMS:
        mp3 = os.path.join(stems6, f'{stem}.mp3')
        if os.path.exists(mp3) and os.path.getsize(mp3) > 5000:
            continue
        # 在 drumsep 子目录查找 WAV
        wav = None
        for search in [ds_dir, stems6]:
            if not os.path.isdir(search):
                continue
            candidates = glob.glob(os.path.join(search, f'{stem}.wav'))
            if not candidates:
                candidates = glob.glob(os.path.join(search, f'*{stem}*.wav'))
            if candidates:
                wav = candidates[0]
                break
        if wav:
            run(f'ffmpeg -y -i "{wav}" -b:a 192k "{mp3}"')
            count += 1
    return song['slug'], count

def phase2_convert(songs):
    print(f'\n{"="*60}')
    print(f'Phase 2: WAV→MP3 转码 ({WORKERS} 线程)')
    print(f'{"="*60}')
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(convert_one, s): s for s in songs}
        for f in as_completed(futs):
            slug, n = f.result()
            if n > 0:
                print(f'  ✅ {slug}: {n} 个 MP3')

# ══════════════════════════════════════════════════════════════
# Phase 3: 分析 JSON（多线程并行）
# ══════════════════════════════════════════════════════════════
SONG_META = {
    "madd3e_-_gi_joe":                     ("MadD3E",   "G.I. Joe",                    "hiphop", "Hip-Hop",         "Hip-Hop",  "⚡"),
    "shosnny_-_dj_shustryi_hip-hop12":     ("Shosnny",  "DJ SHUSTRYI HIP-HOP12",       "hiphop", "Hip-Hop Battle",  "Battle",   "🔥"),
    "shosnny_-_dj_rhakorz_track_44":       ("Shosnny",  "Dj RHAKORZ Track 44",         "hiphop", "Hip-Hop Battle",  "Battle",   "💥"),
    "shosnny_-_franky_dee_ukay_vs_andrey_styl": ("Shosnny", "Franky Dee vs Andrey Stylez", "hiphop", "Battle HipHop", "Battle", "⚔️"),
    "shosnny_-_juste_debout_geneva_diablo_": ("Shosnny", "Juste Debout GENEVA",          "hiphop", "Battle",          "Battle",   "🥊"),
    "shosnny_-_juste_debout2k19_final_wayd": ("Shosnny", "JD2019 Waydi vs Diablo",      "hiphop", "Battle Final",    "Battle",   "👑"),
    "shosnny_-_kod2016__hiphop_final":       ("Shosnny", "KOD2016 中国站 HipHop Final", "hiphop", "Battle",          "Battle",   "🏆"),
    "shosnny_-_nvrmind_x_boybap_-_summertim": ("Shosnny","Nvrmind x Boybap Summertime", "hiphop", "Hip-Hop",         "Hip-Hop",  "☀️"),
    "shosnny_-_sony_track_28":               ("Shosnny", "Sony Track 28",               "hiphop", "Hip-Hop",         "Hip-Hop",  "🎵"),
    "shosnny_-_sony_track_33":               ("Shosnny", "Sony Track 33",               "hiphop", "Hip-Hop",         "Hip-Hop",  "🎶"),
    "shosnny_-_summer_dance_forever_batalla": ("Shosnny", "Summer Dance Forever Battle", "hiphop", "Battle",          "Battle",   "🏖️"),
    "shosnny_-_idk_the_name_of_the_track":   ("Shosnny", "idk the name",                "hiphop", "Hip-Hop",         "Hip-Hop",  "🎤"),
    "vortxbeat_-_larry_jordan_battle":       ("vortxbeat","LARRY JORDAN BATTLE",         "hiphop", "Battle HipHop",   "Battle",   "🥊"),
    "vortxbeat_-_laurent_jordan_battle":     ("vortxbeat","LAURENT JORDAN BATTLE",       "hiphop", "Battle HipHop",   "Battle",   "⚔️"),
    "vortxbeat_-_this_is_hot_what":          ("vortxbeat","This Is Hot What",            "hiphop", "Hip-Hop",         "Hip-Hop",  "🔥"),
}

def analyze_one(song):
    slug = song['slug']
    beats_out = os.path.join(BASE, 'beats', f'{slug}.json')
    if os.path.exists(beats_out) and os.path.getsize(beats_out) > 500:
        return slug, 'skip'

    meta = SONG_META.get(slug)
    if not meta:
        # 尝试模糊匹配
        for k, v in SONG_META.items():
            if slug.startswith(k[:15]):
                meta = v
                break
    if not meta:
        meta = ("Unknown", slug, "hiphop", "Hip-Hop", "Hip-Hop", "🎵")

    artist, title, genre, gname, gshort, icon = meta
    mp3_src = os.path.join(BASE, 'songs_audio', f'{slug}.mp3')
    if not os.path.exists(mp3_src):
        # 尝试找 songs/ 下的原始文件
        candidates = glob.glob(os.path.join(BASE, 'songs', '*.mp3'))
        for c in candidates:
            if slugify(os.path.basename(c)) == slug:
                mp3_src = c
                break

    r = subprocess.run(
        f'python3 analyze_msst.py "{song["stems_dir"]}" "{mp3_src}" '
        f'--genre {genre} --genre-name "{gname}" --genre-short "{gshort}" '
        f'--out "{beats_out}"',
        shell=True, capture_output=True, text=True, cwd=BASE
    )

    if r.returncode == 0 and os.path.exists(beats_out):
        # 注入 meta
        with open(beats_out, 'r', encoding='utf-8') as f:
            d = json.load(f)
        d['artist'] = artist
        d['song'] = title
        d['icon'] = icon
        # 注入 audio_files
        d['audio_files'] = {
            'main':    f'songs_audio/{slug}.mp3',
            'drums':   f'songs_audio/{slug}_stems6/drums.mp3',
            'bass':    f'songs_audio/{slug}_stems6/bass.mp3',
            'guitar':  f'songs_audio/{slug}_stems6/guitar.mp3',
            'piano':   f'songs_audio/{slug}_stems6/piano.mp3',
            'vocals':  f'songs_audio/{slug}_stems6/vocals.mp3',
            'other':   f'songs_audio/{slug}_stems6/other.mp3',
            'kick':    f'songs_audio/{slug}_stems6/kick.mp3',
            'snare':   f'songs_audio/{slug}_stems6/snare.mp3',
            'toms':    f'songs_audio/{slug}_stems6/toms.mp3',
            'hh':      f'songs_audio/{slug}_stems6/hh.mp3',
            'cymbals': f'songs_audio/{slug}_stems6/cymbals.mp3',
        }
        with open(beats_out, 'w', encoding='utf-8') as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        return slug, 'ok'
    else:
        return slug, f'fail: {r.stderr[-200:]}'

def phase3_analyze(songs):
    print(f'\n{"="*60}')
    print(f'Phase 3: 分析 JSON ({WORKERS} 线程)')
    print(f'{"="*60}')

    # 清除旧 JSON
    for jf in glob.glob(os.path.join(BASE, 'beats', '*.json')):
        if os.path.basename(jf) != 'index.json':
            os.remove(jf)

    ok, fail = 0, 0
    with ThreadPoolExecutor(max_workers=WORKERS) as ex:
        futs = {ex.submit(analyze_one, s): s for s in songs}
        for f in as_completed(futs):
            slug, status = f.result()
            if status == 'ok':
                ok += 1
                print(f'  ✅ {slug}')
            elif status == 'skip':
                ok += 1
            else:
                fail += 1
                print(f'  ❌ {slug}: {status}')

    # 更新 index.json
    idx = []
    for jf in sorted(glob.glob(os.path.join(BASE, 'beats', '*.json'))):
        if os.path.basename(jf) == 'index.json':
            continue
        try:
            with open(jf, 'r', encoding='utf-8') as f:
                d = json.load(f)
            idx.append({
                'file': os.path.basename(jf),
                'artist': d.get('artist', ''),
                'song': d.get('song', ''),
                'bpm': d.get('bpm'),
                'key': d.get('key', ''),
                'icon': d.get('icon', '🎵'),
                'genre': d.get('genre', {}),
            })
        except:
            pass
    with open(os.path.join(BASE, 'beats', 'index.json'), 'w', encoding='utf-8') as f:
        json.dump(idx, f, ensure_ascii=False, indent=2)

    print(f'\n✅ Phase 3 完成: {ok} 成功, {fail} 失败')

# ══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    songs = collect_songs()
    print(f'🎵 找到 {len(songs)} 首歌')
    print(f'   已有 DrumSep: {sum(1 for s in songs if s["done"])}')
    print(f'   待处理: {sum(1 for s in songs if not s["done"])}')

    phase1_drumsep(songs)   # GPU 串行（但一次批量推理所有文件）
    phase2_convert(songs)   # 8 线程 WAV→MP3
    phase3_analyze(songs)   # 8 线程分析

    print(f'\n{"="*60}')
    print(f'🎉 全部完成！')

    # git push
    subprocess.run('git add -A && git commit -m "feat: DrumSep AI 鼓组细拆 5轨" && git push',
                   shell=True, cwd=BASE)
