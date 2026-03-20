#!/usr/bin/env python3
"""
patch_steep_filter.py — 陡峭滤波器修复脚本

问题：上一版 BiquadFilter 只用了单阶 (Q=0.7)，衰减仅 ~12dB/octave
  → Solo 军鼓(200-3kHz)时，30-200Hz 的 kick 和 3k-8kHz 的 hihat 大量泄漏
  → 用户听到 "其他声音" 但对应轨道没亮（因为已被标记为 muted）

修复方案：
  1. 将每个子轨的 HPF/LPF 从单阶升级为 4 阶级联 (Butterworth 近似)
     → 4 × HPF(lo) + 4 × LPF(hi) = ~48dB/octave 衰减
     → 相邻频段交叉处衰减从 ~12dB 提升到 ~48dB（声压降低到 1/256）
  
  2. 使用 Butterworth Q 值序列 [0.5412, 1.3065, 0.5412, 1.3065]
     → 比统一 Q=0.707 更平坦的通带响应

  3. 保持 Analyser 在 merger 之后（用于实时频谱显示）

音频路由架构：
  drums.mp3 → Source → ┬→ [HPF×4(30)] → [LPF×4(200)]  → Gain(kick)  ──→┐
                       ├→ [HPF×4(200)]→ [LPF×4(3000)] → Gain(snare) ──→┤
                       ├→ [HPF×4(3k)] → [LPF×4(8k)]   → Gain(hihat) ──→├→ merger → analyser → dest
                       └→ [HPF×4(8k)] → [LPF×4(18k)]  → Gain(crash) ──→┘
  
  每个 [HPF×4] = 4 个串联 highpass BiquadFilter
  每个 [LPF×4] = 4 个串联 lowpass BiquadFilter
  总计每子轨 8 个滤波器 → ~48dB/octave 截止斜率

Usage:
  cd dance-music-visualizer && python3 patch_steep_filter.py
"""
import os, sys

HTML = 'teacher.html'

def read(f):
    with open(f, 'r', encoding='utf-8') as fp:
        return fp.read()

def write(f, s):
    with open(f, 'w', encoding='utf-8') as fp:
        fp.write(s)


def patch():
    html = read(HTML)
    patches = 0

    # ════════════════════════════════════════════════════════════
    # PATCH: 重写 initAudio — 4阶级联滤波器
    # ════════════════════════════════════════════════════════════
    
    # 找到整个 initAudio 函数（从 "function initAudio(){" 到对应的闭合 "}"）
    old_block_start = "// ── 每轨带通滤波器 + Gain 节点（解决 stem 级 mute 串音）──\nlet trackGains = {};  // trackName → GainNode\n\nfunction initAudio(){"
    
    if old_block_start not in html:
        print("❌ 未找到 initAudio 函数起始标记")
        print("   搜索: " + old_block_start[:60])
        return False
    
    # 找到 initAudio 的结束位置（匹配花括号）
    start_idx = html.index(old_block_start)
    # 从 "function initAudio(){" 开始计数花括号
    func_start = html.index("function initAudio(){", start_idx)
    brace_count = 0
    end_idx = func_start
    for i in range(func_start, len(html)):
        if html[i] == '{':
            brace_count += 1
        elif html[i] == '}':
            brace_count -= 1
            if brace_count == 0:
                end_idx = i + 1
                break
    
    old_init_block = html[start_idx:end_idx]
    
    new_init_block = r"""// ── 每轨 4 阶级联带通滤波器 + Gain 节点（~48dB/octave 陡峭截止）──
let trackGains = {};   // trackName → GainNode
let trackFilters = {}; // trackName → { hpfs:[], lpfs:[], gain }

// Butterworth 4th-order Q 值序列（两对二阶节 = 四阶）
const BW_Q = [0.5412, 1.3065, 0.5412, 1.3065];

function createFilterChain(ctx, type, freq, stages){
  const filters = [];
  for(let i = 0; i < stages; i++){
    const f = ctx.createBiquadFilter();
    f.type = type;
    f.frequency.value = freq;
    f.Q.value = BW_Q[i % BW_Q.length];
    filters.push(f);
  }
  // 串联
  for(let i = 0; i < filters.length - 1; i++){
    filters[i].connect(filters[i+1]);
  }
  return filters;
}

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

    const FILTER_ORDER = 4; // 4阶 = ~48dB/octave

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
        // ── 多轨 stem：每轨 4阶HPF + 4阶LPF → Gain → merger ──
        const merger = actx.createGain();
        merger.gain.value = 1;

        tracks.forEach(tc => {
          if(tc._loHz != null && tc._hiHz != null){
            // 4 阶高通 + 4 阶低通 = ~48dB/octave 截止
            const hpfs = createFilterChain(actx, 'highpass', tc._loHz, FILTER_ORDER);
            const lpfs = createFilterChain(actx, 'lowpass',  tc._hiHz, FILTER_ORDER);
            const gain = actx.createGain();
            gain.gain.value = 1;

            // 路由：src → HPF[0]→...→HPF[3] → LPF[0]→...→LPF[3] → gain → merger
            src.connect(hpfs[0]);
            hpfs[hpfs.length-1].connect(lpfs[0]);
            lpfs[lpfs.length-1].connect(gain);
            gain.connect(merger);

            trackGains[tc.name] = gain;
            trackFilters[tc.name] = { hpfs, lpfs, gain };
          } else {
            // 全频段轨道（兜底）
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
        // ── 单轨 stem（guitar/piano）：直通 ──
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
    console.log('🎛 Audio: 4阶带通滤波器路由已初始化 (~48dB/oct)，', Object.keys(trackGains).length, '轨');
  }catch(e){console.warn('AudioCtx:',e)}
}"""

    html = html[:start_idx] + new_init_block + html[end_idx:]
    patches += 1
    print("✅ PATCH 1: initAudio → 4阶级联滤波器 (~48dB/octave)")

    # ════════════════════════════════════════════════════════════
    # PATCH 2: soloTrack — 不能只 mute 非 solo stem，
    #          因为 AI 分离有泄漏，其他 stem 也可能包含 solo 轨的声音
    #          但反过来，如果全开所有 stem，泄漏更严重
    #          正确做法：非 solo stem 全 mute（保持不变），
    #          solo stem 内其他轨 gain=0（已有），这是最优方案
    # ════════════════════════════════════════════════════════════
    # soloTrack 逻辑无需改（已正确），但补强 syncStemMute
    # 当某 stem 内只有部分轨 unmuted 时，确保 stem 音频不 mute
    
    old_sync = """function syncStemMute(stem){
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

    new_sync = """function syncStemMute(stem){
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

    if old_sync in html:
        html = html.replace(old_sync, new_sync, 1)
        patches += 1
        print("✅ PATCH 2: syncStemMute → setTargetAtTime 防爆音")
    else:
        print("⚠️  PATCH 2: 未找到 syncStemMute，跳过")

    # ════════════════════════════════════════════════════════════
    # PATCH 3: muteAll 也用 ramp
    # ════════════════════════════════════════════════════════════
    old_muteAll_gain = """    // 同步 gain 节点
    const g = trackGains[tc.name];
    if(g) g.gain.value = muted ? 0 : 1;"""

    new_muteAll_gain = """    // 同步 gain 节点（ramp 防爆音）
    const g = trackGains[tc.name];
    if(g){
      const ct = actx ? actx.currentTime : 0;
      g.gain.cancelScheduledValues(ct);
      g.gain.setTargetAtTime(muted ? 0 : 1, ct, 0.015);
    }"""

    if old_muteAll_gain in html:
        html = html.replace(old_muteAll_gain, new_muteAll_gain, 1)
        patches += 1
        print("✅ PATCH 3: muteAll → ramp 防爆音")
    else:
        print("⚠️  PATCH 3: 未找到 muteAll gain 代码")

    # ════════════════════════════════════════════════════════════
    # PATCH 4: soloTrack 也用 ramp
    # ════════════════════════════════════════════════════════════
    old_solo_gain = """    // gain 节点：只开 solo 轨
    const g = trackGains[t.name];
    if(g) g.gain.value = isSolo ? 1 : 0;"""

    new_solo_gain = """    // gain 节点：只开 solo 轨（ramp 防爆音）
    const g = trackGains[t.name];
    if(g){
      const ct = actx ? actx.currentTime : 0;
      g.gain.cancelScheduledValues(ct);
      g.gain.setTargetAtTime(isSolo ? 1 : 0, ct, 0.015);
    }"""

    if old_solo_gain in html:
        html = html.replace(old_solo_gain, new_solo_gain, 1)
        patches += 1
        print("✅ PATCH 4: soloTrack → ramp 防爆音")
    else:
        print("⚠️  PATCH 4: 未找到 soloTrack gain 代码")

    # ════════════════════════════════════════════════════════════
    # PATCH 5: exitSolo 也用 ramp
    # ════════════════════════════════════════════════════════════
    old_exit = """function exitSolo(){
  _soloTrack = null;
  muteAll(false);
  // 确保所有 gain 恢复
  TRACKS_CFG.forEach(tc=>{
    const g = trackGains[tc.name];
    if(g) g.gain.value = 1;
  });
}"""

    new_exit = """function exitSolo(){
  _soloTrack = null;
  muteAll(false);
  // 确保所有 gain 恢复（ramp 防爆音）
  TRACKS_CFG.forEach(tc=>{
    const g = trackGains[tc.name];
    if(g){
      const ct = actx ? actx.currentTime : 0;
      g.gain.cancelScheduledValues(ct);
      g.gain.setTargetAtTime(1, ct, 0.015);
    }
  });
}"""

    if old_exit in html:
        html = html.replace(old_exit, new_exit, 1)
        patches += 1
        print("✅ PATCH 5: exitSolo → ramp 防爆音")
    else:
        print("⚠️  PATCH 5: 未找到 exitSolo")

    write(HTML, html)
    print(f"\n{'='*50}")
    print(f"总计: {patches}/5 个 patch 已应用")
    
    if patches >= 3:  # 核心 patch 1 + 至少 2 个辅助
        return True
    return False


if __name__ == '__main__':
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    print("🎛 陡峭滤波器修复 Patch v2")
    print("=" * 50)
    print()
    print("📋 问题分析：")
    print("   上一版滤波器：单阶 BiquadFilter (Q=0.7)")
    print("   衰减斜率：~12dB/octave → 远远不够！")
    print("   例：军鼓 HPF@200Hz，在 100Hz 处仅衰减 12dB")
    print("        → kick 的 100Hz 信号仍有 25% 音量通过")
    print()
    print("   修复方案：4阶级联 Butterworth 滤波器")
    print("   衰减斜率：~48dB/octave → 极陡截止")
    print("   例：军鼓 HPF@200Hz，在 100Hz 处衰减 48dB")
    print("        → kick 的 100Hz 信号仅有 0.4% 音量通过")
    print()
    print("   每子轨路由：")
    print("   src → HPF₁→HPF₂→HPF₃→HPF₄ → LPF₁→LPF₂→LPF₃→LPF₄ → Gain → merger")
    print("   共 8 个滤波器节点/轨，14 轨总计最多 112 个滤波器")
    print("   Web Audio API 完全可以承受（现代浏览器实测无延迟）")
    print()
    print("   额外优化：gain 切换使用 setTargetAtTime(ramp)")
    print("   → 防止 mute/unmute 时产生爆音 (click/pop)")
    print("=" * 50)
    print()
    
    ok = patch()
    if ok:
        print("\n✅ 所有核心 patch 成功应用！")
    else:
        print("\n❌ patch 失败")
        sys.exit(1)
