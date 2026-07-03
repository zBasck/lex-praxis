/* Lex Praxis — JavaScript do frontend */
const LexPravis = (() => {
  const API = "/api/v1";

  async function get(url) {
    const r = await fetch(API + url);
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }
  async function post(url, body) {
    const r = await fetch(API + url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : null,
    });
    if (!r.ok) throw new Error(await r.text());
    return r.json();
  }
  function esc(s) {
    return (s == null ? "" : String(s))
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }
  function brl(s) { return s ? Number(s).toLocaleString("pt-BR", { style: "currency", currency: "BRL" }) : ""; }
  function dateFmt(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.toLocaleDateString("pt-BR");
  }
  function datetimeFmt(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    if (isNaN(d)) return iso;
    return d.toLocaleString("pt-BR");
  }
  function badgeForPrazo(p) {
    if (p.vencido) return "<span class='badge bg-danger'>Vencido</span>";
    if (p.dias_restantes === 0) return "<span class='badge bg-danger'>Hoje</span>";
    if (p.dias_restantes <= 3) return `<span class='badge bg-warning text-dark'>${p.dias_restantes}d</span>`;
    if (p.dias_restantes <= 7) return `<span class='badge bg-info text-dark'>${p.dias_restantes}d</span>`;
    return `<span class='badge bg-light text-dark'>${p.dias_restantes}d</span>`;
  }
  function empty(msg) {
    return `<tr><td colspan="10" class="empty-state"><i class="bi bi-inbox"></i><br>${msg}</td></tr>`;
  }

  // ---------------- Dashboard ----------------
  async function dashboard() {
    try {
      const d = await get("/dashboard");
      document.getElementById("k-proc").textContent = d.kpi.processos_ativos;
      document.getElementById("k-cli").textContent = d.kpi.clientes_ativos;
      document.getElementById("k-pra").textContent = d.kpi.prazos_abertos;
      document.getElementById("k-venc").textContent = d.kpi.prazos_vencidos;
      document.getElementById("k-prox").textContent = d.kpi.prazos_proximos;
      document.getElementById("k-and").textContent = d.kpi.andamentos_30d;

      document.getElementById("prox-prazos").innerHTML = d.proximos_prazos.length
        ? d.proximos_prazos.map(p => `
          <tr class="prazo-row ${p.vencido ? "vencido" : (p.dias_restantes <= 3 ? "critico" : "")}">
            <td>${dateFmt(p.data_limite)}</td>
            <td><a href="/processos/${p.processo_id}">${esc(p.processo_cnj)}</a></td>
            <td>${esc(p.descricao)}</td>
            <td>${badgeForPrazo(p)}</td>
          </tr>`).join("")
        : empty("Sem prazos próximos");

      document.getElementById("ult-andamentos").innerHTML = d.ultimos_andamentos.length
        ? d.ultimos_andamentos.map(a => `
          <li class="list-group-item">
            <div class="d-flex justify-content-between">
              <small class="text-muted">${datetimeFmt(a.capturado_em)}</small>
              <span class="badge bg-light text-dark">${esc(a.fonte || "")}</span>
            </div>
            <div><a href="/processos/${a.processo_id}">${esc(a.texto).slice(0, 120)}</a></div>
            <small class="text-muted">${esc(a.tipo_ato)} ${a.prazo_dias ? `· prazo ${a.prazo_dias}d` : ""}</small>
          </li>`).join("")
        : '<li class="list-group-item text-muted">Sem andamentos.</li>';
    } catch (e) { console.error(e); }
  }

  // ---------------- Processos ----------------
  async function processos() {
    const selTrib = document.getElementById("f-trib");
    const selCli = document.getElementById("sel-trib");
    ["TJSP","TJMS","TJRS","TRF1","TRF2","TRF3","TRF4","TRF5","STJ","STF","DEMO"].forEach(t => {
      selTrib.insertAdjacentHTML("beforeend", `<option>${t}</option>`);
      if (selCli) selCli.insertAdjacentHTML("beforeend", `<option>${t}</option>`);
    });
    const fc = document.getElementById("sel-cli");
    try {
      const cs = await get("/clientes");
      cs.items.forEach(c => fc.insertAdjacentHTML("beforeend", `<option value="${c.id}">${esc(c.nome)}</option>`));
    } catch {}

    const fc2 = document.getElementById("f-cli");
    if (fc2 && fc) {
      fc.querySelectorAll("option").forEach(o => {
        if (o.value) fc2.insertAdjacentHTML("beforeend", `<option value="${o.value}">${o.textContent}</option>`);
      });
    }

    const carregar = async () => {
      const q = document.getElementById("f-q").value;
      const t = selTrib.value;
      const c = fc2 ? fc2.value : "";
      const params = new URLSearchParams();
      if (q) params.set("q", q);
      if (t) params.set("tribunal", t);
      if (c) params.set("cliente_id", c);
      const d = await get("/processos?" + params);
      const tb = document.getElementById("tb-proc");
      tb.innerHTML = d.items.length ? d.items.map(p => `
        <tr>
          <td><a href="/processos/${p.id}">${esc(p.numero_cnj)}</a></td>
          <td><span class="badge bg-secondary">${esc(p.tribunal)}</span></td>
          <td>${esc(p.classe || "—")}</td>
          <td>${esc(p.cliente_nome || "—")}</td>
          <td>${p.proximo_prazo ? dateFmt(p.proximo_prazo) : '<span class="text-muted">—</span>'}</td>
          <td>${p.prazos_vencidos > 0 ? `<span class="badge bg-danger">${p.prazos_vencidos}</span>` : '<span class="text-muted">0</span>'}</td>
          <td><a href="/processos/${p.id}" class="btn btn-sm btn-outline-primary">Abrir</a></td>
        </tr>`).join("") : empty("Nenhum processo");
    };
    ["f-q", "f-trib", "f-cli"].forEach(id => {
      const el = document.getElementById(id);
      if (el) el.addEventListener("input", carregar);
    });
    carregar();

    document.getElementById("f-proc").addEventListener("submit", async (ev) => {
      ev.preventDefault();
      const fd = Object.fromEntries(new FormData(ev.target));
      if (!fd.tribunal) delete fd.tribunal;
      try {
        await post("/processos", fd);
        bootstrap.Modal.getInstance(document.getElementById("m-processo")).hide();
        ev.target.reset();
        carregar();
      } catch (e) {
        alert("Erro: " + e.message);
      }
    });
  }

  // ---------------- Processo detalhe ----------------
  async function processoDetalhe(pid) {
    const carregar = async () => {
      const d = await get(`/processos/${pid}`);
      const la = document.getElementById("lista-and");
      la.innerHTML = d.andamentos.length
        ? `<ul class="timeline">${d.andamentos.map(a => `
            <li>
              <div class="data">${datetimeFmt(a.data)} · <span class="tipo">${esc(a.tipo_ato)}</span> · ${esc(a.fonte || "")}</div>
              <div>${esc(a.texto)}</div>
              ${a.prazo_dias ? `<small class="text-danger"><b>Prazo:</b> ${a.prazo_dias} dias · ${esc(a.tarefa_sugerida || "")}</small><br>` : ""}
              ${a.resumo_cliente ? `<small class="text-muted"><i>${esc(a.resumo_cliente)}</i></small>` : ""}
            </li>`).join("")}</ul>`
        : '<div class="empty-state"><i class="bi bi-hourglass"></i><br>Sem andamentos ainda. Clique em "Atualizar" para buscar no tribunal.</div>';

      const lp = document.getElementById("lista-prz");
      lp.innerHTML = d.prazos.length
        ? `<table class="table table-hover"><thead><tr><th>Data limite</th><th>Descrição</th><th>Status</th><th></th></tr></thead>
           <tbody>${d.prazos.map(p => `
            <tr class="prazo-row ${p.vencido ? "vencido" : (p.dias_restantes <= 3 ? "critico" : "")}">
              <td>${dateFmt(p.data_limite)}</td>
              <td>${esc(p.descricao)}</td>
              <td>${badgeForPrazo(p)} <span class="text-muted">${esc(p.status)}</span></td>
              <td>
                ${p.status === "aberto" ? `<button class="btn btn-sm btn-success" data-concluir="${p.id}"><i class="bi bi-check2"></i></button>
                 <button class="btn btn-sm btn-outline-secondary" data-cancelar="${p.id}"><i class="bi bi-x"></i></button>` : ""}
              </td>
            </tr>`).join("")}</tbody></table>`
        : '<div class="empty-state"><i class="bi bi-hourglass-bottom"></i><br>Sem prazos registrados.</div>';

      document.querySelectorAll("[data-concluir]").forEach(b =>
        b.onclick = async () => { await post(`/prazos/${b.dataset.concluir}/concluir`); carregar(); });
      document.querySelectorAll("[data-cancelar]").forEach(b =>
        b.onclick = async () => { await post(`/prazos/${b.dataset.cancelar}/cancelar`); carregar(); });
    };
    carregar();
    document.getElementById("btn-harvest").onclick = async () => {
      const r = await post(`/processos/${pid}/harvest`);
      alert(`Capturado: ${r.andamentos_novos} andamentos, ${r.prazos_novos} prazos`);
      carregar();
    };
    document.getElementById("f-and").onsubmit = async (ev) => {
      ev.preventDefault();
      const fd = Object.fromEntries(new FormData(ev.target));
      if (fd.data) {
        const d = new Date(fd.data);
        fd.data = d.toISOString();
      }
      try {
        await post("/andamentos", { ...fd, processo_id: pid });
        ev.target.reset();
        carregar();
      } catch (e) { alert("Erro: " + e.message); }
    };
  }

  // ---------------- Clientes ----------------
  async function clientes() {
    const carregar = async () => {
      const q = document.getElementById("f-q").value;
      const d = await get("/clientes" + (q ? "?q=" + encodeURIComponent(q) : ""));
      document.getElementById("tb-cli").innerHTML = d.items.length
        ? d.items.map(c => `
          <tr>
            <td>${esc(c.nome)}</td><td>${esc(c.documento || "—")}</td>
            <td>${esc(c.tipo)}</td><td>${esc(c.email || "—")}</td>
            <td>${esc(c.phone || "—")}</td>
            <td>${c.processos_count}</td>
          </tr>`).join("")
        : empty("Nenhum cliente");
    };
    document.getElementById("f-q").oninput = carregar;
    document.getElementById("f-cli").onsubmit = async (ev) => {
      ev.preventDefault();
      const fd = Object.fromEntries(new FormData(ev.target));
      try { await post("/clientes", fd); bootstrap.Modal.getInstance(document.getElementById("m-cli")).hide(); ev.target.reset(); carregar(); }
      catch (e) { alert("Erro: " + e.message); }
    };
    carregar();
  }

  // ---------------- Prazos ----------------
  async function prazos() {
    const carregar = async () => {
      const s = document.getElementById("f-status").value;
      const h = document.getElementById("f-hor").value;
      const params = new URLSearchParams();
      params.set("status", s);
      if (h) params.set("horizon", h);
      const d = await get("/prazos?" + params);
      document.getElementById("tb-prz").innerHTML = d.items.length
        ? d.items.map(p => {
            const cnj = p.processo_cnj || ("#" + p.processo_id);
            const trib = p.processo_tribunal ? ` <span class="badge bg-light text-dark">${esc(p.processo_tribunal)}</span>` : "";
            return `
          <tr class="prazo-row ${p.vencido ? "vencido" : (p.dias_restantes <= 3 ? "critico" : "")}">
            <td>${dateFmt(p.data_limite)}</td>
            <td>${badgeForPrazo(p)}</td>
            <td><a href="/processos/${p.processo_id}" class="link-primary">${esc(cnj)}</a>${trib}</td>
            <td>${esc(p.descricao)}</td>
            <td>${p.dias_restantes >= 0 ? p.dias_restantes + " dias" : ("vencido ha " + Math.abs(p.dias_restantes) + " dias")}</td>
            <td><span class="badge bg-light text-dark">${esc(p.prioridade || "normal")}</span></td>
            <td>
              ${p.status === "aberto" ? `<button class="btn btn-sm btn-success" data-con="${p.id}" title="Concluir prazo"><i class="bi bi-check2"></i></button>
               <button class="btn btn-sm btn-outline-danger" data-cnc="${p.id}" title="Cancelar prazo"><i class="bi bi-x"></i></button>` : `<span class="text-muted small">${esc(p.status)}</span>`}
            </td>
          </tr>`;}).join("")
        : empty("Sem prazos nesse filtro");
      document.querySelectorAll("[data-con]").forEach(b =>
        b.onclick = async () => { await post(`/prazos/${b.dataset.con}/concluir`); carregar(); });
      document.querySelectorAll("[data-cnc]").forEach(b =>
        b.onclick = async () => { await post(`/prazos/${b.dataset.cnc}/cancelar`); carregar(); });
    };
    document.getElementById("f-status").onchange = carregar;
    document.getElementById("f-hor").onchange = carregar;
    carregar();
  }

  // ---------------- Agenda ----------------
  async function agenda() {
    let cur = new Date();
    cur.setDate(1);
    const carregar = async () => {
      const ini = new Date(cur.getFullYear(), cur.getMonth(), 1);
      const fim = new Date(cur.getFullYear(), cur.getMonth() + 1, 0);
      const params = new URLSearchParams();
      params.set("status", "aberto");
      params.set("horizon", "60");
      const d = await get("/prazos?" + params);
      const prazos = d.items;
      const head = ["Dom","Seg","Ter","Qua","Qui","Sex","Sáb"];
      document.getElementById("cal-head").innerHTML = head.map(h => `<th>${h}</th>`).join("");
      document.getElementById("mes-label").textContent =
        ini.toLocaleDateString("pt-BR", { month: "long", year: "numeric" });

      const tbody = document.getElementById("cal-body");
      tbody.innerHTML = "";
      const today = new Date(); today.setHours(0,0,0,0);
      let row = "<tr>";
      for (let i = 0; i < ini.getDay(); i++) row += "<td class='cal-day'></td>";
      for (let dia = 1; dia <= fim.getDate(); dia++) {
        const cellDate = new Date(cur.getFullYear(), cur.getMonth(), dia);
        if (cellDate.getDay() === 0 && dia > 1) { row += "</tr><tr>"; }
        const isoDay = cellDate.toISOString().slice(0, 10);
        const doDia = prazos.filter(p => p.data_limite === isoDay);
        const isToday = cellDate.getTime() === today.getTime();
        const cls = ["cal-day"];
        if (isToday) cls.push("today");
        if (doDia.length) cls.push("has-prazo");
        const pills = doDia.map(p => {
          const tone = p.vencido ? "" : (p.dias_restantes <= 3 ? "warn" : "ok");
          return `<a href="/processos/${p.processo_id}" class="prazo-pill ${tone}" title="${esc(p.descricao)}">${dateFmt(p.data_limite)} · ${esc(p.descricao).slice(0, 24)}</a>`;
        }).join("");
        row += `<td class="${cls.join(" ")}"><div class="date-num">${dia}</div>${pills}</td>`;
      }
      while (row.endsWith("<td></td>") || !row.includes(`>${fim.getDate()}</div>`)) { row += "<td></td>"; if (row.split("</tr><tr>").length > 5) break; }
      row += "</tr>";
      tbody.innerHTML = row;
    };
    document.getElementById("prev-month").onclick = () => { cur.setMonth(cur.getMonth() - 1); carregar(); };
    document.getElementById("next-month").onclick = () => { cur.setMonth(cur.getMonth() + 1); carregar(); };
    document.getElementById("today").onclick = () => { cur = new Date(); cur.setDate(1); carregar(); };
    carregar();
  }

  return { dashboard, processos, processoDetalhe, clientes, prazos, agenda };
})();
