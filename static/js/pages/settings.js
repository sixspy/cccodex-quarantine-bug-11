import { api } from '../api.js';
import { loadRulepack, rulepackStrip } from '../rulepack.js';

export async function renderSettings(el) {
  const data = await api('/api/settings');
  el.innerHTML = `
    <div class="card">
      <h2>台参数</h2>
      <table>
        <thead><tr><th>项</th><th>说明</th><th>值</th><th></th></tr></thead>
        <tbody>
          ${(data.items || []).map((s) => `
            <tr>
              <td>${s.key}</td>
              <td>${s.label}</td>
              <td><input data-key="${s.key}" value="${s.value}" /></td>
              <td><button data-save="${s.key}">保存</button></td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
  el.querySelectorAll('[data-save]').forEach((btn) => {
    btn.onclick = async () => {
      const input = el.querySelector(`input[data-key="${btn.dataset.save}"]`);
      await api('/api/settings/update', {
        method: 'POST',
        body: JSON.stringify({ key: btn.dataset.save, value: input.value }),
      });
      await renderSettings(el);
    };
  });

  const rp = await loadRulepack();
  el.innerHTML += `<div class="card" style="margin-top:1rem">
    <h3>规则包（规则条只读口径）</h3>
    ${rulepackStrip(rp)}
    <table>
      <thead><tr><th>账册#</th><th>包键</th><th>版本</th><th>规则指纹</th><th>钉版人</th><th>时间</th><th>钉点</th></tr></thead>
      <tbody>
        ${(rp.ledger || []).map((r) => `
          <tr>
            <td>${r.id}</td>
            <td>${r.pack_key}</td>
            <td>v${r.pack_version}</td>
            <td>${r.rules_fp}</td>
            <td>${r.actor}</td>
            <td>${r.created_at}</td>
            <td>${r.active ? '<span class="chip ok">现行钉点</span>' : ''}</td>
          </tr>`).join('')}
      </tbody>
    </table>
    <div class="row" style="margin-top:10px">
      <input id="rpKey" value="${rp.pack_key}" placeholder="包键" />
      <input id="rpNote" placeholder="升版备注" />
      <button id="rpUpgrade" type="button">升版钉死</button>
      <span id="rpMsg" class="err"></span>
    </div>
    <p class="muted">升版把当前规则指纹钉进切流账册并拨动钉点；两名仓管同抢只有一人成，另一人收白话回滚提示。</p>
  </div>`;
  el.querySelector('#rpUpgrade').onclick = async () => {
    try {
      await api('/api/rulepack/upgrade', {
        method: 'POST',
        body: JSON.stringify({
          pack_key: el.querySelector('#rpKey').value,
          note: el.querySelector('#rpNote').value,
          expect_version: rp.pack_version,
        }),
      });
    } catch (e) {
      el.querySelector('#rpMsg').textContent = e.message;
      return;
    }
    await renderSettings(el);
  };
}
