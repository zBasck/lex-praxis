// Lex-Praxis - Frontend JS
window.LexPravis = window.LexPravis || {};

LexPravis.toast = (msg, tipo='info') => {
  const el = document.createElement('div');
  el.className = 'toast align-items-center text-white bg-' + (tipo==='erro'?'danger':tipo==='ok'?'success':'primary') + ' border-0 show';
  el.style.cssText = 'position:fixed;top:20px;right:20px;z-index:9999;min-width:250px;';
  el.innerHTML = '<div class="d-flex"><div class="toast-body">' + msg + '</div><button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast"></button></div>';
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 4500);
};

LexPravis.fmtData = (d) => { if (!d) return '-'; return new Date(d).toLocaleDateString('pt-BR'); };
LexPravis.fmtDataHora = (d) => { if (!d) return '-'; return new Date(d).toLocaleString('pt-BR'); };
LexPravis.fmtDias = (n) => n == null ? '-' : (n < 0 ? 'vencido ' + Math.abs(n) + 'd' : n + 'd');
LexPravis.onlyDigits = (s) => (s || '').replace(/\D/g, '');

LexPravis.api = async (path, options = {}) => {
  const r = await fetch(path, options);
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.error || r.statusText);
  }
  return r.json();
};

LexPravis.processoDetalhe = (PID) => {
  const elAnd = document.getElementById('lista-and');
  const elPrz = document.getElementById('lista-prz');
  if (!elAnd || !elPrz) return;

  async function load() {
    const p = await LexPravis.api('/api/v1/processos/' + PID);
    document.title = p.numero_cnj + ' - Lex-Praxis';
    elAnd.innerHTML = '';
    elPrz.innerHTML = '';

    if (!p.andamentos.length) {
      elAnd.innerHTML = '<p class="text-muted">Nenhum andamento registrado.</p>';
    } else {
      p.andamentos.forEach(a => {
        elAnd.innerHTML += '<div class="border-start border-3 ps-3 mb-3"><div class="small text-muted">' + LexPravis.fmtDataHora(a.data) + ' - <b>' + (a.tipo_ato || '-') + '</b> - ' + (a.fonte || '') + '</div><div>' + ((a.texto || '').slice(0, 500)) + '</div>' + (a.tarefa_sugerida ? '<div class="small text-primary mt-1"><i class="bi bi-arrow-right"></i> ' + a.tarefa_sugerida + '</div>' : '') + '</div>';
      });
    }

    if (!p.prazos.length) {
      elPrz.innerHTML = '<p class="text-muted">Nenhum prazo vinculado.</p>';
    } else {
      p.prazos.forEach(z => {
        const venc = z.vencido ? 'bg-danger text-white' : (z.dias_restantes < 3 ? 'bg-warning' : 'bg-light text-dark');
        elPrz.innerHTML += '<div class="border rounded p-2 mb-2 ' + venc + '"><div class="d-flex justify-content-between"><div><b>' + (z.descricao || z.tipo || 'Prazo') + '</b></div><span class="small">#' + z.id + '</span></div><div class="small">Vence em ' + LexPravis.fmtData(z.data_limite) + ' (' + LexPravis.fmtDias(z.dias_restantes) + ') - <b>' + z.status + '</b></div>' + (z.status === 'aberto' ? '<button class="btn btn-sm btn-outline-success mt-1" data-concluir="' + z.id + '">Concluir prazo</button>' : '<span class="badge bg-success">concluido em ' + LexPravis.fmtData(z.concluido_em) + '</span>') + '</div>';
      });
      elPrz.querySelectorAll('[data-concluir]').forEach(b => {
        b.onclick = async () => {
          if (!confirm('Marcar este prazo como concluido?')) return;
          await LexPravis.api('/api/v1/prazos/' + b.dataset.concluir + '/concluir', {method: 'POST'});
          LexPravis.toast('Prazo concluido!', 'ok');
          load();
        };
      });
    }
  }
  load();

  const fAnd = document.getElementById('f-and');
  if (fAnd) fAnd.onsubmit = async (e) => {
    e.preventDefault();
    const fd = new FormData(fAnd);
    const body = {texto: fd.get('texto'), data: fd.get('data') ? new Date(fd.get('data')).toISOString() : new Date().toISOString()};
    await LexPravis.api('/api/v1/processos/' + PID + '/andamento', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
    fAnd.reset();
    load();
  };

  const btnH = document.getElementById('btn-harvest');
  if (btnH) btnH.onclick = async () => {
    btnH.disabled = true; btnH.innerHTML = 'Atualizando...';
    const j = await LexPravis.api('/api/v1/processos/' + PID + '/atualizar-dje', {method: 'POST'}).catch(e => ({erro: e.message}));
    LexPravis.toast('Andamentos novos: ' + (j.andamentos_novos || 0) + ', Prazos: ' + (j.prazos_novos || 0) + '. Status: ' + (j.status || '?'), 'ok');
    load();
  };
};
