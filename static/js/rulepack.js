import { api } from './api.js';

// 规则包统一读轨：甲路切流账册。全台各屏只认这一套包引用。
export async function loadRulepack() {
  return await api('/api/rulepack');
}

// 三件分清：徽标(badge) / 包版本号(version) / 规则包落点行(landing)
export function rulepackStrip(rp) {
  const cls = rp.aligned ? 'ok' : 'bad';
  return `<div class="rulepack-strip" data-track="${rp.read_track}">
    <span class="chip ${cls}" data-role="rulepack-badge">${rp.badge}</span>
    <span class="chip" data-role="rulepack-version">包版本 ${rp.pack_key} v${rp.pack_version}</span>
    <span class="muted" data-role="rulepack-landing">落点 ${rp.landing} · 现行指纹 ${rp.live_fp}</span>
    <span class="err" data-role="rulepack-msg"></span>
  </div>`;
}

export function showRulepackError(el, e) {
  const slot = el.querySelector('[data-role="rulepack-msg"]');
  if (slot) slot.textContent = (e && e.message) || String(e);
}
