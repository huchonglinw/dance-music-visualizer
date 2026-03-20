#!/usr/bin/env python3
"""
patch_audio_filter.py — 音频分轨修复 Patch 脚本

修复问题：
  1. 子轨视觉层级：多轨 stem 下的子轨行左侧加缩进
  2. 音频串音根因：当前 mute 在 stem 级别（6个 <audio>），
     solo 底鼓 = 播放整个 drums.mp3 → 听到所有鼓声+AI泄漏
  3. 解决方案：在 Web Audio API 中为每个子轨插入 BiquadFilter(bandpass)
     + GainNode，mute 子轨时 gain=0，只让对应频段通过

深度分析报告：
  ┌─ drums.mp3 ─┐
  │  kick 30-200Hz       ← 只想听这个
  │  snare 200-3kHz      ← 但 stem mute 是全有或全无
  │  hihat 3k-8kHz       ← 所以"刀出剑鞘"是 snare 泛音
  │  crash 8k-18kHz      ← "擦擦声"是 hihat
  │  + AI残余鸟叫/环境声 ← htdemucs 分离不完美
  └──────────────┘

  ┌─ other.mp3 ─┐
  │  AI 分离后的残余     ← 包含鼓声泄漏（尤其kick低频）
  │  synth 200-4kHz      ← 因此 solo 合成器听到鼓声
  │  fx 4k-20kHz
  │  pad 20-200Hz
  └──────────────┘

  解决方案架构：
  drums.mp3 → Source → ┬→ BPF(30-200) → Gain(kick) ──→┐
                       ├→ BPF(200-3k) → Gain(snare) ──→┤
                       ├→ BPF(3k-8k)  → Gain(hihat) ──→├→ Analyser → dest
                       └→ BPF(8k-18k) → Gain(crash) ──→┘

  每个 Gain 的值由 trackMuted[name] 控制：
    muted → gain.value = 0
    unmuted → gain.value = 1

Usage:
  python3 patch_audio_filter.py
"""
import re, sys, os

HTML = 'teacher.html'

def read(f):
    with open(f, 'r', encoding='utf-8') as fp:
        return fp.read()

def write(f, s):
    with open(f, 'w', encoding='utf-8') as fp:
        fp.write(s)

def patch_html():
    html = read(HTML)
    patches_applied = 0

    # ════════════════════════════════════════════════════════════
    # PATCH 1: 子轨缩进 CSS
    # ════════════════════════════════════════════════════════════
    old_tr_css = "/* 单轨道行 */\n.tr{display:flex;align-items:stretch;height:32px;border-bottom:1px solid rgba(255,255,255,.03);\n  transition:background .08s;position:relative;overflow:hidden}"
    new_tr_css = """/* 单轨道行 */
.tr{display:flex;align-items:stretch;height:32px;border-bottom:1px solid rgba(255,255,255,.03);
  transition:background .08s;position:relative;overflow:hidden}
.tr.sub-track{padding-left:14px}
.tr.sub-track .tr-label{border-left:2px solid rgba(255,255,255,.06);margin-left:0;padding-left:4px}"""

    if old_tr_css in html:
        html = html.replace(old_tr_css, new_tr_css, 1)
        patches_applied += 1
        print("✅ PATCH 1: 子轨缩进 CSS 已添加")
    else:
        print("⚠️  PATCH 1: 未找到 CSS 锚点，尝试备选...")
        # 备选：直接在 .tr{ 定义后插入
        if '.tr{display:flex;align-items:stretch;height:32px' in html:
            idx = html.index('.tr{display:flex;align-items:stretch;height:32px')
            end = html.index('}', idx) + 1
            html = html[:end] + '\n.tr.sub-track{padding-left:14px}\n.tr.sub-track .tr-label{border-left:2px solid rgba(255,255,255,.06);margin-left:0;padding-left:4px}' + html[end:]
            patches_applied += 1
            print("✅ PATCH 1 (备选): 子轨缩进 CSS 已添加")
        else:
            print("❌ PATCH 1: 完全找不到插入点")

    # ════════════════════════════════════════════════════════════
    # PATCH 2: buildDAW 中为多轨 stem 的子轨添加 sub-track class
    # ════════════════════════════════════════════════════════════
    old_row_class = "      row.className='tr';row.id='tr-'+tc.name;"
    new_row_class = "      const isSubTrack = tracks.length > 1;\n      row.className='tr'+(isSubTrack?' sub-track':'');row.id='tr-'+tc.name;"

    if old_row_class in html:
        html = html.replace(old_row_class, new_row_class, 1)
        patches_applied += 1
        print("✅ PATCH 2: 子轨 sub-track class 已添加")
    else:
        print("❌ PATCH 2: 未找到 row.className 锚点")

    # ════════════════════════════════════════════════════════════
    # PATCH 3: 重写 initAudio — 带通滤波器 + GainNode 路由
    # ════════════════════════════════════════════════════════════
    old_init = """function initAudio(){
  if(_ready)return;
  try{
    actx=new(window.AudioContext||window.webkitAudioContext)();
    AUD.volume=0;AUD.muted=true;
    ['drums','bass','guitar','piano','vocals','other'].forEach(n=>{
      const a=actx.createAnalyser();
      a.fftSize=FFT;a.smoothingTimeConstant=0.72;a.minDecibels=-95;a.maxDecibels=-5;
      const s=actx.createMediaElementSource(STEM_AUDS[n]);
      s.connect(a);a.connect(actx.destination);
      stemAnalysers[n]=a;stemSrcs[n]=s;
    });
    _ready=true;
  }catch(e){console.warn('AudioCtx:',e)}
}"""

    new_init = r"""// ── 每轨带通滤波器 + Gain 节点（解决 stem 级 mute 串音）──
let trackGains = {};  // trackName → GainNode

function initAudio(){
  if(_ready)return;
  try{
    actx=new(window.AudioContext||window.webkitAudioContext)();
    AUD.volume=0;AUD.muted=true;

    // 按 stem 分组 TRACKS_CFG
    const stemTracks = {};
    TRACKS_CFG.forEach(tc=>{
      if(!stemTracks[tc.stem]) stemTracks[tc.stem]=[];
      stemTracks[tc.stem].push(tc);
    });

    ['drums','bass','guitar','piano','vocals','other'].forEach(stemName=>{
      const src = actx.createMediaElementSource(STEM_AUDS[stemName]);
      stemSrcs[stemName] = src;

      // Analyser（用于实时频谱显示）
      const analyser = actx.createAnalyser();
      analyser.fftSize=FFT; analyser.smoothingTimeConstant=0.72;
      analyser.minDecibels=-95; analyser.maxDecibels=-5;
      stemAnalysers[stemName] = analyser;

      const tracks = stemTracks[stemName] || [];
      const hasBandTracks = tracks.some(tc => tc._loHz != null && tc._hiHz != null);

      if(hasBandTracks && tracks.length > 1){
        // ── 多轨 stem：每轨一个 BPF → Gain → merger ──
        // src → 各子轨 BPF → Gain → merger → analyser → dest
        const merger = actx.createGain();
        merger.gain.value = 1;

        tracks.forEach(tc => {
          if(tc._loHz != null && tc._hiHz != null){
            // 带频段的轨道：用双重滤波器（高通+低通）精确截断
            const hpf = actx.createBiquadFilter();
            hpf.type = 'highpass'; hpf.frequency.value = tc._loHz; hpf.Q.value = 0.7;
            const lpf = actx.createBiquadFilter();
            lpf.type = 'lowpass'; lpf.frequency.value = tc._hiHz; lpf.Q.value = 0.7;
            const gain = actx.createGain();
            gain.gain.value = 1;

            src.connect(hpf);
            hpf.connect(lpf);
            lpf.connect(gain);
            gain.connect(merger);

            trackGains[tc.name] = gain;
          } else {
            // 全频段轨道（不应出现在多轨stem中，但兜底）
            const gain = actx.createGain();
            gain.gain.value = 1;
            src.connect(gain);
            gain.connect(merger);
            trackGains[tc.name] = gain;
          }
        });

        merger.connect(analyser);
        analyser.connect(actx.destination);

      } else {
        // ── 单轨 stem（guitar/piano）或无频段信息：直通 ──
        const gain = actx.createGain();
        gain.gain.value = 1;
        src.connect(gain);
        gain.connect(analyser);
        analyser.connect(actx.destination);

        if(tracks.length === 1){
          trackGains[tracks[0].name] = gain;
        } else {
          tracks.forEach(tc => {
            trackGains[tc.name] = gain;
          });
        }
      }
    });
    _ready=true;
    console.log('🎛 Audio: 带通滤波器路由已初始化，', Object.keys(trackGains).length, '个轨道增益节点');
  }catch(e){console.warn('AudioCtx:',e)}
}"""

    if old_init in html:
        html = html.replace(old_init, new_init, 1)
        patches_applied += 1
        print("✅ PATCH 3: initAudio 带通滤波器路由已重写")
    else:
        print("❌ PATCH 3: 未找到 initAudio 函数")

    # ════════════════════════════════════════════════════════════
    # PATCH 4: syncStemMute → 改为 per-track gain 控制
    # ════════════════════════════════════════════════════════════
    old_sync = """function syncStemMute(stem){
  const allTracksOfStem = TRACKS_CFG.filter(t=>t.stem===stem);
  const allMuted = allTracksOfStem.every(t=>trackMuted[t.name]);
  if(STEM_AUDS[stem]) STEM_AUDS[stem].muted = allMuted;
  stemMuted[stem] = allMuted;
}"""

    new_sync = """function syncStemMute(stem){
  const allTracksOfStem = TRACKS_CFG.filter(t=>t.stem===stem);
  const allMuted = allTracksOfStem.every(t=>trackMuted[t.name]);
  // stem 音频 mute：只有全部子轨 muted 才 mute 音频源
  if(STEM_AUDS[stem]) STEM_AUDS[stem].muted = allMuted;
  stemMuted[stem] = allMuted;
  // per-track gain 控制：精确频段静音
  allTracksOfStem.forEach(tc=>{
    const g = trackGains[tc.name];
    if(g) g.gain.value = trackMuted[tc.name] ? 0 : 1;
  });
}"""

    if old_sync in html:
        html = html.replace(old_sync, new_sync, 1)
        patches_applied += 1
        print("✅ PATCH 4: syncStemMute → per-track gain 控制")
    else:
        print("❌ PATCH 4: 未找到 syncStemMute")

    # ════════════════════════════════════════════════════════════
    # PATCH 5: muteAll → 同步 trackGains
    # ════════════════════════════════════════════════════════════
    old_muteAll = """function muteAll(muted){
  _soloTrack = null;
  TRACKS_CFG.forEach(tc=>{
    trackMuted[tc.name] = muted;
    const btn = document.getElementById('mx-'+tc.name);
    if(btn){ btn.classList.toggle('muted', muted); btn.classList.toggle('on', !muted); btn.classList.remove('solo'); }
  });
  Object.keys(STEM_AUDS).forEach(k=>{ STEM_AUDS[k].muted = muted; stemMuted[k] = muted; });
}"""

    new_muteAll = """function muteAll(muted){
  _soloTrack = null;
  TRACKS_CFG.forEach(tc=>{
    trackMuted[tc.name] = muted;
    const btn = document.getElementById('mx-'+tc.name);
    if(btn){ btn.classList.toggle('muted', muted); btn.classList.toggle('on', !muted); btn.classList.remove('solo'); }
    // 同步 gain 节点
    const g = trackGains[tc.name];
    if(g) g.gain.value = muted ? 0 : 1;
  });
  Object.keys(STEM_AUDS).forEach(k=>{ STEM_AUDS[k].muted = muted; stemMuted[k] = muted; });
}"""

    if old_muteAll in html:
        html = html.replace(old_muteAll, new_muteAll, 1)
        patches_applied += 1
        print("✅ PATCH 5: muteAll → 同步 trackGains")
    else:
        print("❌ PATCH 5: 未找到 muteAll")

    # ════════════════════════════════════════════════════════════
    # PATCH 6: soloTrack → 同步 trackGains + 不 mute stem 音频
    # ════════════════════════════════════════════════════════════
    old_solo = """function soloTrack(name){
  _soloTrack = name;
  const tc = TRACKS_CFG.find(t=>t.name===name);
  const soloStem = tc?.stem;
  TRACKS_CFG.forEach(t=>{
    const isSolo = (t.name===name);
    trackMuted[t.name] = !isSolo;
    const btn = document.getElementById('mx-'+t.name);
    if(btn){
      btn.classList.toggle('muted', !isSolo);
      btn.classList.toggle('on', isSolo);
      btn.classList.toggle('solo', isSolo);
    }
  });
  // 音频：只开 solo 轨所在的 stem
  Object.keys(STEM_AUDS).forEach(k=>{
    STEM_AUDS[k].muted = (k !== soloStem);
    stemMuted[k] = (k !== soloStem);
  });
}"""

    new_solo = """function soloTrack(name){
  _soloTrack = name;
  const tc = TRACKS_CFG.find(t=>t.name===name);
  const soloStem = tc?.stem;
  TRACKS_CFG.forEach(t=>{
    const isSolo = (t.name===name);
    trackMuted[t.name] = !isSolo;
    const btn = document.getElementById('mx-'+t.name);
    if(btn){
      btn.classList.toggle('muted', !isSolo);
      btn.classList.toggle('on', isSolo);
      btn.classList.toggle('solo', isSolo);
    }
    // gain 节点：只开 solo 轨
    const g = trackGains[t.name];
    if(g) g.gain.value = isSolo ? 1 : 0;
  });
  // 音频源：所有 stem 都不 mute（让滤波器去控制）
  // 只 mute 完全不相关的 stem（非 solo 轨所在 stem）
  Object.keys(STEM_AUDS).forEach(k=>{
    STEM_AUDS[k].muted = (k !== soloStem);
    stemMuted[k] = (k !== soloStem);
  });
}"""

    if old_solo in html:
        html = html.replace(old_solo, new_solo, 1)
        patches_applied += 1
        print("✅ PATCH 6: soloTrack → per-track gain + stem 过滤")
    else:
        print("❌ PATCH 6: 未找到 soloTrack")

    # ════════════════════════════════════════════════════════════
    # PATCH 7: exitSolo → 恢复所有 gain
    # ════════════════════════════════════════════════════════════
    old_exit = """function exitSolo(){
  _soloTrack = null;
  muteAll(false);
}"""

    new_exit = """function exitSolo(){
  _soloTrack = null;
  muteAll(false);
  // 确保所有 gain 恢复
  TRACKS_CFG.forEach(tc=>{
    const g = trackGains[tc.name];
    if(g) g.gain.value = 1;
  });
}"""

    if old_exit in html:
        html = html.replace(old_exit, new_exit, 1)
        patches_applied += 1
        print("✅ PATCH 7: exitSolo → 恢复所有 gain")
    else:
        print("❌ PATCH 7: 未找到 exitSolo")

    write(HTML, html)
    print(f"\n{'='*50}")
    print(f"总计: {patches_applied}/7 个 patch 已应用")
    if patches_applied < 7:
        print("⚠️  部分 patch 未找到锚点，请手动检查！")
        return False
    return True


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print("🎛 音频分轨修复 Patch")
    print("="*50)
    print()
    print("📋 深度分析报告：")
    print("   问题1: Solo 底鼓时听到擦擦声/鸟叫/剑鞘声")
    print("   原因:  mute 在 stem 级别，solo kick = 播放整个 drums.mp3")
    print("          drums.mp3 包含 kick+snare+hihat+crash+AI残留")
    print("          '擦擦声' = hihat 泄漏，'剑鞘声' = snare 泛音")
    print("          '鸟叫' = htdemucs AI分离不完美的残余")
    print()
    print("   问题2: Solo 合成器听到鼓声")
    print("   原因:  solo synth = 播放整个 other.mp3")
    print("          other.mp3 中有 AI 分离残留的鼓声（尤其 kick 低频）")
    print()
    print("   解决:  Web Audio BiquadFilter(highpass+lowpass) 精确频段隔离")
    print("          每个子轨一组滤波器 + GainNode")
    print("          mute 子轨 → gain=0，只有对应频段通过")
    print()
    print("   问题3: 子轨视觉层级不明显")
    print("   解决:  多轨 stem 子轨添加 .sub-track class + CSS 缩进")
    print("="*50)
    print()

    ok = patch_html()
    if ok:
        print("\n✅ 所有 patch 成功应用！")
    else:
        print("\n⚠️  部分 patch 失败，请检查")
        sys.exit(1)
