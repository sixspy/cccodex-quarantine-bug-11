import { api } from '../api.js';
import { loadRulepack, rulepackStrip, showRulepackError } from '../rulepack.js';

export async function renderReview(el) {
  const [data, rp] = await Promise.all([
    api('/api/tickets'),
    loadRulepack(),
  ]);
  el.innerHTML = `
    <div class="card">
      <h2>复核放行</h2>
      ${rulepackStrip(rp)}
      <table>
        <thead><tr><th>单号</th><th>条目</th><th>舱</th><th>裁决</th><th>操作</th></tr></thead>
        <tbody>
          ${(data.items || []).map((t) => `
            <tr>
              <td>${t.ticket_code}</td>
              <td>${t.item_key}</td>
              <td>${t.bin_code}</td>
              <td><span class="chip">${t.decision}</span></td>
              <td class="row">
                ${t.decision === '待决' ? `
                  <button data-d="放行" data-id="${t.id}">放行</button>
                  <button data-d="驳回回炉" data-id="${t.id}">驳回回炉</button>
                  <button data-d="废弃" data-id="${t.id}">废弃</button>
                ` : (t.comment || '')}
              </td>
            </tr>`).join('')}
        </tbody>
      </table>
    </div>`;
  el.querySelectorAll('button[data-d]').forEach((btn) => {
    btn.onclick = async () => {
      try {
        await api(`/api/tickets/${btn.dataset.id}/decide`, {
          method: 'POST',
          body: JSON.stringify({
            decision: btn.dataset.d,
            comment: '台上裁决',
            pack_fp: rp.rules_fp,
            pack_version: rp.pack_version,
          }),
        });
      } catch (e) {
        showRulepackError(el, e);
        return;
      }
      await renderReview(el);
    };
  });
}
