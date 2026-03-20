#!/usr/bin/env python3
"""
upgrade_drumsep.py — 一键升级：补全方案 B 环节 2（DrumSep 鼓组细拆）

这个脚本做 4 件事：
  1. 检查 MSST 仓库 + DrumSep 模型权重是否就位
  2. 修改 process_songs.py：stem 分离后增加 DrumSep 步骤
  3. 修改 analyze_msst.py：鼓组从频率滤波改为读取 DrumSep 输出文件
  4. 修改 teacher.html：增加鼓组子轨音频元素 + 移除 BiquadFilter 架构

用法:
  python3 upgrade_drumsep.py          # 安装依赖 + 修改代码
  python3 upgrade_drumsep.py --run    # 安装 + 修改 + 重跑全部歌曲
"""
import os, sys, subprocess, re, json, glob

BASE = os.path.dirname(os.path.abspath(__file__))
MSST_DIR = os.path.join(BASE, 'Music-Source-Separation-Training')
MODEL_DIR = os.path.join(BASE, 'models')
DRUMSEP_CONFIG_URL = 'https://github.com/jarredou/models/releases/download/DrumSep/config_mdx23c.yaml'
DRUMSEP_WEIGHTS_URL = 'https://github.com/jarredou/models/releases/download/DrumSep/drumsep_5stems_mdx23c_jarredou.ckpt'
DRUMSEP_CONFIG = os.path.join(MODEL_DIR, 'drumsep_config.yaml')
DRUMSEP_WEIGHTS = os.path.join(MODEL_DIR, 'drumsep_5stems_mdx23c_jarredou.ckpt')

# DrumSep 5 轨输出名
DRUM_STEMS = ['kick', 'snare', 'toms', 'hh', 'cymbals']


def run(cmd, **kw):
    print(f'  $ {cmd}')
    return subprocess.run(cmd, shell=True, **kw)


def step1_install():
    """检查/安装 MSST + DrumSep 模型"""
    print('\n' + '='*60)
    print('步骤 1: 检查 MSST 仓库 + DrumSep 模型')
    print('='*60)

    # 1a. Clone MSST
    if not os.path.exists(MSST_DIR):
        print('📦 克隆 Music-Source-Separation-Training...')
        run(f'git clone --depth 1 https://github.com/ZFTurbo/Music-Source-Separation-Training.git "{MSST_DIR}"')
    else:
        print('✅ MSST 仓库已存在')

    # 1b. 安装依赖
    req_file = os.path.join(MSST_DIR, 'requirements.txt')
    if os.path.exists(req_file):
        print('📦 安装 MSST 依赖...')
        run(f'pip install -q -r "{req_file}"')
    
    # 1c. 下载 DrumSep 模型
    os.makedirs(MODEL_DIR, exist_ok=True)
    if not os.path.exists(DRUMSEP_WEIGHTS):
        print(f'📥 下载 DrumSep 模型权重 (~400MB)...')
        run(f'curl -L -o "{DRUMSEP_WEIGHTS}" "{DRUMSEP_WEIGHTS_URL}"')
    else:
        print(f'✅ DrumSep 权重已存在: {os.path.getsize(DRUMSEP_WEIGHTS)/(1024*1024):.0f}MB')

    if not os.path.exists(DRUMSEP_CONFIG):
        print(f'📥 下载 DrumSep 配置...')
        run(f'curl -L -o "{DRUMSEP_CONFIG}" "{DRUMSEP_CONFIG_URL}"')
    else:
        print('✅ DrumSep 配置已存在')

    print('✅ 步骤 1 完成')


def step2_patch_process_songs():
    """修改 process_songs.py：添加 DrumSep 步骤"""
    print('\n' + '='*60)
    print('步骤 2: 修改 process_songs.py')
    print('='*60)

    fpath = os.path.join(BASE, 'process_songs.py')
    with open(fpath, 'r', encoding='utf-8') as f:
        code = f.read()

    # 检查是否已经有 DrumSep 步骤
    if 'drumsep' in code.lower() or 'drum_sep' in code:
        print('⏭  process_songs.py 已包含 DrumSep 步骤，跳过')
        return

    # ── 在 phase2_process 中，WAV→MP3 部分之后、分析之前，插入 DrumSep 步骤 ──
    # 找到 "# 分析" 标记位置
    marker = '        # 分析\n        print(f"📊 [{song}] 分析'
    if marker not in code:
        # 尝试更宽松的匹配
        marker = "        # 分析\n"
        if marker not in code:
            print('⚠️  无法在 process_songs.py 中找到插入点，请手动修改')
            return

    drumsep_block = '''        # ── DrumSep：鼓组细拆（drums.wav → kick/snare/toms/hh/cymbals）──
        drums_wav = glob.glob(os.path.join(stems_dir, "*(Drums)*.wav"))
        if not drums_wav:
            drums_wav = glob.glob(os.path.join(stems_dir, "*Drums*.wav"))
        drumsep_dir = os.path.join(stems6, "drumsep")
        drumsep_done = os.path.exists(drumsep_dir) and len(glob.glob(drumsep_dir+"/*.wav")) >= 4
        if drums_wav and not drumsep_done:
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
            r = run(f'cd "{msst_dir}" && python inference.py '
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
                # 转 MP3
                for ds in ["kick","snare","toms","hh","cymbals"]:
                    wav_pat = os.path.join(drumsep_dir, f"*{ds}*.wav")
                    wavs = glob.glob(wav_pat)
                    # MSST 输出文件名格式：drums_(instrument).wav
                    if not wavs:
                        wavs = glob.glob(os.path.join(drumsep_dir, f"drums_({ds}).wav"))
                    if not wavs:
                        wavs = glob.glob(os.path.join(drumsep_dir, f"*({ds})*.wav"))
                    if wavs:
                        mp3_dst = os.path.join(stems6, f"{ds}.mp3")
                        run(f'ffmpeg -y -i "{wavs[0]}" -b:a 192k "{mp3_dst}"')
                print(f"✅ [{song}] DrumSep 完成")
        elif drumsep_done:
            print(f"⏭  [{song}] DrumSep 已存在")

'''

    code = code.replace(marker, drumsep_block + marker)

    # ── 更新 audio_files 字典，增加鼓组子轨 ──
    old_audio = """d.update({'artist':artist,'song':song,'icon':icon,'audio_files':{
            'main':f'songs_audio/{slug}.mp3',
            'drums':f'songs_audio/{slug}_stems6/drums.mp3',
            'bass':f'songs_audio/{slug}_stems6/bass.mp3',
            'guitar':f'songs_audio/{slug}_stems6/guitar.mp3',
            'piano':f'songs_audio/{slug}_stems6/piano.mp3',
            'vocals':f'songs_audio/{slug}_stems6/vocals.mp3',
            'other':f'songs_audio/{slug}_stems6/other.mp3',
        }})"""

    new_audio = """d.update({'artist':artist,'song':song,'icon':icon,'audio_files':{
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
        }})"""

    code = code.replace(old_audio, new_audio)

    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(code)

    print('✅ process_songs.py 已更新（添加 DrumSep 步骤 + 鼓组音频路径）')


def step3_patch_analyze():
    """修改 analyze_msst.py：鼓组改用 DrumSep 输出文件"""
    print('\n' + '='*60)
    print('步骤 3: 修改 analyze_msst.py')
    print('='*60)

    fpath = os.path.join(BASE, 'analyze_msst.py')
    with open(fpath, 'r', encoding='utf-8') as f:
        code = f.read()

    if 'drumsep' in code.lower():
        print('⏭  analyze_msst.py 已包含 DrumSep 逻辑，跳过')
        return

    # ── 1. 替换鼓组 TRACKS_CONFIG：从 band 改为 full（读独立文件） ──
    old_drums_config = """    # ── 鼓组 4 子轨（kick/snare/hihat/crash 频段完全不重叠）──
    {'name': 'kick',      'stem': 'drums',  'type': 'band',
     'lo': 30,   'hi': 200,   'thresh': 0.30, 'min_gap': 3,
     'label': 'Kick 底鼓',     'icon': '🥁', 'color': '#ff3b30', 'freq': '30-200Hz'},
    {'name': 'snare',     'stem': 'drums',  'type': 'band',
     'lo': 200,  'hi': 3000,  'thresh': 0.30, 'min_gap': 4,
     'label': 'Snare 军鼓',    'icon': '💥', 'color': '#ff9f0a', 'freq': '200-3kHz'},
    # cymbals 拆分：hihat 短促金属声(3k-8k) vs crash/ride 持续亮镲(8k-18k)
    {'name': 'hihat',     'stem': 'drums',  'type': 'band',
     'lo': 3000, 'hi': 8000,  'thresh': 0.20, 'min_gap': 2,
     'label': 'Hi-Hat 踩镲',   'icon': '🔔', 'color': '#ffd60a', 'freq': '3k-8kHz'},
    {'name': 'crash',     'stem': 'drums',  'type': 'band',
     'lo': 8000, 'hi': 18000, 'thresh': 0.22, 'min_gap': 3,
     'label': 'Crash 亮镲',    'icon': '💥', 'color': '#ffe066', 'freq': '8k-18kHz'},"""

    new_drums_config = """    # ── 鼓组 5 子轨（DrumSep AI 分离，每轨独立音频文件）──
    {'name': 'kick',      'stem': 'kick',     'type': 'full',
     'thresh': 0.30, 'min_gap': 3,
     'label': 'Kick 底鼓',     'icon': '🥁', 'color': '#ff3b30', 'freq': 'AI分离'},
    {'name': 'snare',     'stem': 'snare',    'type': 'full',
     'thresh': 0.30, 'min_gap': 4,
     'label': 'Snare 军鼓',    'icon': '💥', 'color': '#ff9f0a', 'freq': 'AI分离'},
    {'name': 'toms',      'stem': 'toms',     'type': 'full',
     'thresh': 0.25, 'min_gap': 3,
     'label': 'Toms 嗵鼓',     'icon': '🪘', 'color': '#ff6b35', 'freq': 'AI分离'},
    {'name': 'hh',        'stem': 'hh',       'type': 'full',
     'thresh': 0.20, 'min_gap': 2,
     'label': 'Hi-Hat 踩镲',   'icon': '🔔', 'color': '#ffd60a', 'freq': 'AI分离'},
    {'name': 'cymbals',   'stem': 'cymbals',  'type': 'full',
     'thresh': 0.22, 'min_gap': 3,
     'label': 'Cymbals 镲片',  'icon': '🎶', 'color': '#ffe066', 'freq': 'AI分离'},"""

    code = code.replace(old_drums_config, new_drums_config)

    # ── 2. 修改 find_stem_file 以支持 drumsep 子目录查找 ──
    old_find = """def find_stem_file(stems_dir, stem_name):
    \"\"\"在 audio-separator / demucs 输出目录中找指定 stem\"\"\"
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
    return None"""

    new_find = """def find_stem_file(stems_dir, stem_name):
    \"\"\"在 audio-separator / demucs / drumsep 输出目录中找指定 stem\"\"\"
    # DrumSep 子轨：优先在 drumsep/ 子目录查找
    drumsep_stems = {'kick', 'snare', 'toms', 'hh', 'cymbals'}
    if stem_name.lower() in drumsep_stems:
        # 先找 stems6 目录下的 drumsep 子目录
        parent = os.path.dirname(stems_dir)
        slug = os.path.basename(stems_dir).replace('_stems', '')
        stems6_dir = os.path.join(parent, '..', 'songs_audio', slug + '_stems6', 'drumsep')
        if os.path.isdir(stems6_dir):
            ds_patterns = [
                os.path.join(stems6_dir, f'*({stem_name})*.wav'),
                os.path.join(stems6_dir, f'*{stem_name}*.wav'),
                os.path.join(stems6_dir, f'{stem_name}.wav'),
            ]
            for pat in ds_patterns:
                matches = glob.glob(pat, recursive=False)
                if matches:
                    return matches[0]
        # 也检查 stems6 目录下直接的 mp3
        stems6_mp3 = os.path.join(parent, '..', 'songs_audio', slug + '_stems6', f'{stem_name}.mp3')
        if os.path.exists(stems6_mp3):
            return stems6_mp3

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
    return None"""

    code = code.replace(old_find, new_find)

    # ── 3. 修改 STEM_NAMES 列表以包含 DrumSep 子轨 ──
    old_stem_load = "    STEM_NAMES = ['Drums', 'Bass', 'Guitar', 'Piano', 'Vocals', 'Other']"
    new_stem_load = "    STEM_NAMES = ['Drums', 'Bass', 'Guitar', 'Piano', 'Vocals', 'Other', 'kick', 'snare', 'toms', 'hh', 'cymbals']"
    code = code.replace(old_stem_load, new_stem_load)

    # ── 4. 更新 audio_files 字典 ──
    old_audio_files = """    audio_files = {
        'main': f'songs_audio/{slug}.mp3',
        'drums':  f'songs_audio/{slug}_stems6/drums.mp3',
        'bass':   f'songs_audio/{slug}_stems6/bass.mp3',
        'guitar': f'songs_audio/{slug}_stems6/guitar.mp3',
        'piano':  f'songs_audio/{slug}_stems6/piano.mp3',
        'vocals': f'songs_audio/{slug}_stems6/vocals.mp3',
        'other':  f'songs_audio/{slug}_stems6/other.mp3',
    }"""

    new_audio_files = """    audio_files = {
        'main': f'songs_audio/{slug}.mp3',
        'drums':  f'songs_audio/{slug}_stems6/drums.mp3',
        'bass':   f'songs_audio/{slug}_stems6/bass.mp3',
        'guitar': f'songs_audio/{slug}_stems6/guitar.mp3',
        'piano':  f'songs_audio/{slug}_stems6/piano.mp3',
        'vocals': f'songs_audio/{slug}_stems6/vocals.mp3',
        'other':  f'songs_audio/{slug}_stems6/other.mp3',
        'kick':     f'songs_audio/{slug}_stems6/kick.mp3',
        'snare':    f'songs_audio/{slug}_stems6/snare.mp3',
        'toms':     f'songs_audio/{slug}_stems6/toms.mp3',
        'hh':       f'songs_audio/{slug}_stems6/hh.mp3',
        'cymbals':  f'songs_audio/{slug}_stems6/cymbals.mp3',
    }"""

    code = code.replace(old_audio_files, new_audio_files)

    # ── 5. 更新 separation_model 标识 ──
    code = code.replace(
        "'separation_model': 'htdemucs_6s (6-stem AI)'",
        "'separation_model': 'htdemucs_6s + DrumSep mdx23c (6+5 stem AI)'"
    )

    # ── 6. 更新注释头 ──
    code = code.replace(
        '轨道结构 (14轨):',
        '轨道结构 (15轨 — DrumSep AI 鼓组细拆版):'
    )
    code = code.replace(
        '  鼓组 4子轨  : kick / snare / hihat / crash       (drums AI轨 → 频段滤波)',
        '  鼓组 5子轨  : kick / snare / toms / hh / cymbals  (drums AI轨 → DrumSep AI细拆)'
    )

    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(code)

    print('✅ analyze_msst.py 已更新（鼓组改为 DrumSep AI 分离 + 5 轨）')


def step4_patch_teacher_html():
    """修改 teacher.html：
    1. 增加鼓组子轨 <audio> 元素
    2. STEM_AUDS 增加鼓组子轨
    3. initAudio 改为独立音频元素架构（移除 BiquadFilter）
    """
    print('\n' + '='*60)
    print('步骤 4: 修改 teacher.html')
    print('='*60)

    fpath = os.path.join(BASE, 'teacher.html')
    with open(fpath, 'r', encoding='utf-8') as f:
        code = f.read()

    if 'aud-kick' in code:
        print('⏭  teacher.html 已包含鼓组子轨音频元素，跳过')
        return

    # ── 1. 在 aud-other 之后增加鼓组子轨 <audio> 元素 ──
    old_audio_els = '''<audio id="aud-other" src="songs_audio/stems6/other.mp3" preload="auto" crossorigin="anonymous"></audio>'''
    new_audio_els = '''<audio id="aud-other" src="songs_audio/stems6/other.mp3" preload="auto" crossorigin="anonymous"></audio>
<audio id="aud-kick" src="" preload="auto" crossorigin="anonymous"></audio>
<audio id="aud-snare" src="" preload="auto" crossorigin="anonymous"></audio>
<audio id="aud-toms" src="" preload="auto" crossorigin="anonymous"></audio>
<audio id="aud-hh" src="" preload="auto" crossorigin="anonymous"></audio>
<audio id="aud-cymbals" src="" preload="auto" crossorigin="anonymous"></audio>'''
    code = code.replace(old_audio_els, new_audio_els)

    # ── 2. STEM_AUDS 增加鼓组子轨 ──
    old_stem_auds = '''const STEM_AUDS = {
  drums:  document.getElementById('aud-drums'),
  bass:   document.getElementById('aud-bass'),
  guitar: document.getElementById('aud-guitar'),
  piano:  document.getElementById('aud-piano'),
  vocals: document.getElementById('aud-vocals'),
  other:  document.getElementById('aud-other'),
};'''
    new_stem_auds = '''const STEM_AUDS = {
  drums:  document.getElementById('aud-drums'),
  bass:   document.getElementById('aud-bass'),
  guitar: document.getElementById('aud-guitar'),
  piano:  document.getElementById('aud-piano'),
  vocals: document.getElementById('aud-vocals'),
  other:  document.getElementById('aud-other'),
  kick:     document.getElementById('aud-kick'),
  snare:    document.getElementById('aud-snare'),
  toms:     document.getElementById('aud-toms'),
  hh:       document.getElementById('aud-hh'),
  cymbals:  document.getElementById('aud-cymbals'),
};'''
    code = code.replace(old_stem_auds, new_stem_auds)

    # ── 3. stemMuted 增加鼓组子轨 ──
    old_stem_muted = 'const stemMuted = {drums:false,bass:false,guitar:false,piano:false,vocals:false,other:false};'
    new_stem_muted = 'const stemMuted = {drums:false,bass:false,guitar:false,piano:false,vocals:false,other:false,kick:false,snare:false,toms:false,hh:false,cymbals:false};'
    code = code.replace(old_stem_muted, new_stem_muted)

    # ── 4. 重写 initAudio：移除 BiquadFilter，改为独立音频元素架构 ──
    # 找到旧的 initAudio 函数并替换
    old_init_start = "// ── 每轨 4 阶级联带通滤波器 + Gain 节点（~48dB/octave 陡峭截止）──"
    old_init_end = "  console.log('🎛 Audio: 4阶带通滤波器路由已初始化 (~48dB/oct)，', Object.keys(trackGains).length, '轨');\n  }catch(e){console.warn('AudioCtx:',e)}\n}"

    new_init = """// ── 每轨独立 audio 元素 + GainNode（无滤波器，DrumSep AI 分离）──
let trackGains = {};   // trackName → GainNode

function initAudio(){
  if(_ready)return;
  try{
    actx=new(window.AudioContext||window.webkitAudioContext)();
    AUD.volume=0;AUD.muted=true;

    // 鼓组子轨映射：如果有独立 kick/snare/toms/hh/cymbals 音频
    // 则鼓组子轨直接使用独立音频源，drums 主轨 mute（避免重复）
    const hasDrumSep = !!(STEM_AUDS.kick?.src && STEM_AUDS.kick.src !== '');

    // 收集所有需要接入的 stem 名称
    const allStems = ['drums','bass','guitar','piano','vocals','other'];
    if(hasDrumSep) allStems.push('kick','snare','toms','hh','cymbals');

    allStems.forEach(stemName=>{
      const aud = STEM_AUDS[stemName];
      if(!aud || !aud.src) return;

      const src = actx.createMediaElementSource(aud);
      stemSrcs[stemName] = src;

      const analyser = actx.createAnalyser();
      analyser.fftSize=FFT; analyser.smoothingTimeConstant=0.72;
      analyser.minDecibels=-95; analyser.maxDecibels=-5;
      stemAnalysers[stemName] = analyser;

      const gain = actx.createGain();
      gain.gain.value = 1;

      // 如果有 DrumSep，drums 主轨静音（避免和子轨重复）
      if(hasDrumSep && stemName === 'drums'){
        gain.gain.value = 0;
      }

      src.connect(gain);
      gain.connect(analyser);
      analyser.connect(actx.destination);

      // 为该 stem 下的所有轨道共享同一个 gain
      const tracks = TRACKS_CFG.filter(tc => tc.stem === stemName);
      tracks.forEach(tc => {
        trackGains[tc.name] = gain;
      });

      // 如果没有轨道映射到这个 stem（比如 drums 主轨），也记录
      if(tracks.length === 0){
        trackGains[stemName] = gain;
      }
    });

    _ready=true;
    console.log('🎛 Audio: DrumSep 独立音频架构已初始化，', Object.keys(trackGains).length, '轨');
  }catch(e){console.warn('AudioCtx:',e)}
}"""

    # 找到并替换
    init_start_idx = code.find(old_init_start)
    init_end_idx = code.find(old_init_end)
    if init_start_idx != -1 and init_end_idx != -1:
        code = code[:init_start_idx] + new_init + code[init_end_idx + len(old_init_end):]
    else:
        print('⚠️  无法定位 initAudio 函数，请手动替换')
        return

    # ── 5. 修改 syncStemMute：鼓组子轨直接控制独立音频 ──
    old_sync = """function syncStemMute(stem){
  const allTracksOfStem = TRACKS_CFG.filter(t=>t.stem===stem);
  const allMuted = allTracksOfStem.every(t=>trackMuted[t.name]);
  // stem 音频 mute：只有全部子轨 muted 才 mute 音频源
  if(STEM_AUDS[stem]) STEM_AUDS[stem].muted = allMuted;
  stemMuted[stem] = allMuted;
  // per-track gain 控制：精确频段静音（使用 ramp 避免爆音）
  allTracksOfStem.forEach(tc=>{
    const g = trackGains[tc.name];
    if(g){
      const t = actx ? actx.currentTime : 0;
      g.gain.cancelScheduledValues(t);
      g.gain.setTargetAtTime(trackMuted[tc.name] ? 0 : 1, t, 0.015);
    }
  });
}"""

    new_sync = """function syncStemMute(stem){
  const allTracksOfStem = TRACKS_CFG.filter(t=>t.stem===stem);
  allTracksOfStem.forEach(tc=>{
    // 每个子轨直接控制自己的 stem audio 元素
    const aud = STEM_AUDS[tc.stem];
    if(aud) { aud.muted = trackMuted[tc.name]; stemMuted[tc.stem] = trackMuted[tc.name]; }
    // gain 节点控制
    const g = trackGains[tc.name];
    if(g){
      const t = actx ? actx.currentTime : 0;
      g.gain.cancelScheduledValues(t);
      g.gain.setTargetAtTime(trackMuted[tc.name] ? 0 : 1, t, 0.015);
    }
  });
}"""
    code = code.replace(old_sync, new_sync)

    # ── 6. 修改 soloTrack：支持独立音频 ──
    old_solo = """  // 音频源：所有 stem 都不 mute（让滤波器去控制）
  // 只 mute 完全不相关的 stem（非 solo 轨所在 stem）
  Object.keys(STEM_AUDS).forEach(k=>{
    STEM_AUDS[k].muted = (k !== soloStem);
    stemMuted[k] = (k !== soloStem);
  });"""

    new_solo = """  // 音频源：只打开 solo 轨对应的 stem，其他全 mute
  Object.keys(STEM_AUDS).forEach(k=>{
    // drums 主轨始终 mute（DrumSep 子轨替代）
    if(k === 'drums' && STEM_AUDS.kick?.src) { STEM_AUDS[k].muted = true; stemMuted[k] = true; return; }
    STEM_AUDS[k].muted = (k !== soloStem);
    stemMuted[k] = (k !== soloStem);
  });"""
    code = code.replace(old_solo, new_solo)

    # ── 7. 更新 loadSong 的音频加载逻辑 ──
    old_load = """    if(d.audio_files){
      AUD.src=d.audio_files.main||'';
      Object.keys(STEM_AUDS).forEach(k=>{
        if(d.audio_files[k])STEM_AUDS[k].src=d.audio_files[k];
      });
      Object.values(STEM_AUDS).forEach(a=>a.load());
    }"""

    new_load = """    if(d.audio_files){
      AUD.src=d.audio_files.main||'';
      Object.keys(STEM_AUDS).forEach(k=>{
        if(d.audio_files[k]) STEM_AUDS[k].src=d.audio_files[k];
        else STEM_AUDS[k].src=''; // 清空不存在的轨道
      });
      Object.values(STEM_AUDS).forEach(a=>{if(a.src)a.load();});
    }"""
    code = code.replace(old_load, new_load)

    # ── 8. 更新 muteAll 和 exitSolo ──
    old_muteall_stem = "  Object.keys(STEM_AUDS).forEach(k=>{ STEM_AUDS[k].muted = muted; stemMuted[k] = muted; });"
    new_muteall_stem = """  Object.keys(STEM_AUDS).forEach(k=>{
    // drums 主轨始终 mute（DrumSep 子轨替代）
    if(k === 'drums' && STEM_AUDS.kick?.src) { STEM_AUDS[k].muted = true; stemMuted[k] = true; return; }
    STEM_AUDS[k].muted = muted; stemMuted[k] = muted;
  });"""
    code = code.replace(old_muteall_stem, new_muteall_stem)

    # ── 9. 更新 play/pause/sync 以包含新的音频元素 ──
    # 这些已经用 Object.values(STEM_AUDS) 遍历，自动包含新元素，无需修改

    # ── 10. 更新 getTime 使用 kick 而不是 drums（因为 drums 被 mute） ──
    old_gettime = "function getTime(){return STEM_AUDS.drums.currentTime||0;}"
    new_gettime = "function getTime(){return (STEM_AUDS.kick?.currentTime || STEM_AUDS.drums.currentTime)||0;}"
    code = code.replace(old_gettime, new_gettime)

    # ── 11. 更新 loadedmetadata 事件 ──
    old_meta = """STEM_AUDS.drums.addEventListener('loadedmetadata',()=>{
  TOTAL=STEM_AUDS.drums.duration;
  document.getElementById('tt').textContent=fmt(TOTAL);
});"""
    new_meta = """// 用 kick（DrumSep）或 drums（回退）获取时长
(STEM_AUDS.kick || STEM_AUDS.drums).addEventListener('loadedmetadata',()=>{
  TOTAL=(STEM_AUDS.kick?.duration || STEM_AUDS.drums.duration);
  document.getElementById('tt').textContent=fmt(TOTAL);
});
STEM_AUDS.drums.addEventListener('loadedmetadata',()=>{
  if(!TOTAL) { TOTAL=STEM_AUDS.drums.duration; document.getElementById('tt').textContent=fmt(TOTAL); }
});"""
    code = code.replace(old_meta, new_meta)

    # ── 12. 更新 ended 事件 ──
    old_ended = "STEM_AUDS.drums.addEventListener('ended',()=>{_playing=false;document.getElementById('pb').textContent='▶';});"
    new_ended = "(STEM_AUDS.kick || STEM_AUDS.drums).addEventListener('ended',()=>{_playing=false;document.getElementById('pb').textContent='▶';});"
    code = code.replace(old_ended, new_ended)

    with open(fpath, 'w', encoding='utf-8') as f:
        f.write(code)

    print('✅ teacher.html 已更新（DrumSep 独立音频架构，移除 BiquadFilter）')


def step5_reprocess():
    """删除现有分析结果，重跑全部歌曲"""
    print('\n' + '='*60)
    print('步骤 5: 重跑全部歌曲')
    print('='*60)

    # 删除现有 beats JSON（强制重新分析）
    beats_dir = os.path.join(BASE, 'beats')
    for jf in glob.glob(os.path.join(beats_dir, '*.json')):
        if os.path.basename(jf) != 'index.json':
            os.remove(jf)
            print(f'  🗑  删除: {os.path.basename(jf)}')

    # 运行 process_songs.py
    print('🔄 重新处理所有歌曲...')
    run(f'python3 process_songs.py', cwd=BASE)


def step6_push():
    """Git add + commit + push"""
    print('\n' + '='*60)
    print('步骤 6: Git push')
    print('='*60)
    run(f'cd "{BASE}" && git add -A && git commit -m "feat: DrumSep AI 鼓组细拆 — 修复鼓组串音问题" && git push', cwd=BASE)


if __name__ == '__main__':
    print('🚀 DrumSep 升级脚本')
    print(f'   工作目录: {BASE}')

    step1_install()
    step2_patch_process_songs()
    step3_patch_analyze()
    step4_patch_teacher_html()

    if '--run' in sys.argv:
        step5_reprocess()
        step6_push()
    else:
        print('\n' + '='*60)
        print('✅ 代码修改完成！')
        print('   接下来手动执行:')
        print(f'   cd {BASE}')
        print('   python3 process_songs.py     # 重跑全部歌曲')
        print('   git add -A && git commit -m "feat: DrumSep" && git push')
        print('')
        print('   或直接: python3 upgrade_drumsep.py --run')
