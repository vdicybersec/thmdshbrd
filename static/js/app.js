/* THM dashboard - progressive enhancement only; every page works without JS except refresh. */
(() => {
  'use strict';

  const $ = (sel, root = document) => root.querySelector(sel);
  const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

  /* ---------- Broken images: avatar -> initial, others -> keep layout, hide ---------- */
  document.addEventListener('error', (e) => {
    const img = e.target;
    if (!(img instanceof HTMLImageElement)) return;
    if (img.classList.contains('avatar')) {
      const span = document.createElement('span');
      span.className = img.className + ' avatar--fallback';
      span.setAttribute('aria-hidden', 'true');
      span.textContent = (img.dataset.initial || '?').toUpperCase();
      img.replaceWith(span);
    } else {
      img.classList.add('img-missing');
    }
  }, true);

  /* ---------- Toast ---------- */
  const toastEl = $('#toast');
  let toastTimer;
  function toast(msg, ms = 4000) {
    if (!toastEl) return;
    toastEl.textContent = msg;
    toastEl.dataset.show = 'true';
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => { toastEl.dataset.show = 'false'; }, ms);
  }

  /* ---------- Relative time ("5 menit lalu") ---------- */
  const rtf = new Intl.RelativeTimeFormat('id', { numeric: 'auto' });
  function relative(iso) {
    const diff = (new Date(iso) - Date.now()) / 1000;
    const abs = Math.abs(diff);
    if (abs < 60) return 'baru saja';
    if (abs < 3600) return rtf.format(Math.round(diff / 60), 'minute');
    if (abs < 86400) return rtf.format(Math.round(diff / 3600), 'hour');
    return rtf.format(Math.round(diff / 86400), 'day');
  }
  function updateRelative() {
    $$('time[data-relative]').forEach((t) => {
      if (t.dateTime) t.textContent = relative(t.dateTime);
    });
  }
  updateRelative();
  setInterval(updateRelative, 30000);

  /* ---------- Refresh buttons ---------- */
  $$('[data-refresh]').forEach((btn) => {
    const label = $('[data-label]', btn);
    const original = label.textContent;
    const reset = () => { btn.removeAttribute('aria-busy'); btn.disabled = false; label.textContent = original; };

    btn.addEventListener('click', async () => {
      btn.disabled = true;
      btn.setAttribute('aria-busy', 'true');
      label.textContent = 'Memulai…';
      try {
        const res = await fetch(btn.dataset.refresh, { method: 'POST' });
        const body = await res.json().catch(() => ({}));
        if (body.status === 'started') {
          let left = body.eta_seconds || 60;
          toast(`Sync berjalan. Halaman akan dimuat ulang otomatis dalam ±${left} detik.`, 5000);
          const tick = () => {
            label.textContent = `Sinkronisasi… ${left} dtk`;
            if (left-- <= 0) window.location.reload();
            else setTimeout(tick, 1000);
          };
          tick();
        } else if (body.status === 'throttled') {
          toast(`Data baru saja diperbarui. Coba lagi dalam ${body.retry_after} detik.`);
          reset();
        } else {
          toast(`Refresh gagal: ${body.message || 'server tidak merespons'}`);
          reset();
        }
      } catch {
        toast('Refresh gagal: tidak bisa menghubungi server.');
        reset();
      }
    });
  });

  /* ---------- Tooltip for heatmap / week strip ---------- */
  const tip = $('#tooltip');
  function showTip(el) {
    if (!tip || !el.dataset.tip) return;
    tip.textContent = el.dataset.tip;
    const r = el.getBoundingClientRect();
    tip.style.left = `${r.left + r.width / 2}px`;
    tip.style.top = `${r.top}px`;
    tip.hidden = false;
  }
  document.addEventListener('pointerover', (e) => {
    const el = e.target.closest('[data-tip]');
    if (el) showTip(el); else if (tip) tip.hidden = true;
  });
  document.addEventListener('scroll', () => { if (tip) tip.hidden = true; }, true);

  /* ---------- Clickable rows (link inside stays the accessible target) ---------- */
  $$('tr[data-href]').forEach((row) => {
    row.addEventListener('click', (e) => {
      if (e.target.closest('a, button')) return;
      if (e.metaKey || e.ctrlKey) window.open(row.dataset.href, '_blank');
      else window.location.href = row.dataset.href;
    });
  });

  /* ---------- Search + segmented filter (shared by leaderboard and rooms) ---------- */
  function wireFilter(root, matchFilter, unit, limit = 0) {
    if (!root) return;
    const input = $('[data-search]', root);
    const buttons = $$('[data-filter]', root);
    const rows = $$('tbody tr', root);
    const empty = $('[data-empty]', root);
    const count = $('[data-result-count]', root);
    const table = $('.table-wrap', root);
    let filter = 'all';
    let expanded = false;

    // "Show more" for long lists; only applies while no search/filter is active.
    let moreWrap; let moreBtn;
    if (limit && rows.length > limit) {
      moreWrap = document.createElement('div');
      moreWrap.className = 'more';
      moreWrap.style.paddingBottom = 'var(--space-4)';
      moreBtn = document.createElement('button');
      moreBtn.type = 'button';
      moreBtn.className = 'btn btn--secondary';
      moreBtn.setAttribute('aria-expanded', 'false');
      moreBtn.addEventListener('click', () => { expanded = !expanded; apply(); });
      moreWrap.appendChild(moreBtn);
      (empty || table).after(moreWrap);
    }

    function apply() {
      const q = (input?.value || '').trim().toLowerCase();
      const narrowing = Boolean(q) || filter !== 'all';
      let shown = 0;
      rows.forEach((row) => {
        const text = `${row.dataset.name || ''} ${row.dataset.username || ''}`;
        const ok = (!q || text.includes(q)) && (filter === 'all' || matchFilter(row, filter));
        if (ok) shown += 1;
        row.hidden = !ok || (moreBtn && !narrowing && !expanded && shown > limit);
      });
      if (empty) empty.hidden = shown > 0;
      if (table) table.hidden = shown === 0;
      if (count) count.textContent = shown === rows.length ? '' : `${shown} dari ${rows.length} ${unit}`;
      if (moreBtn) {
        moreWrap.hidden = narrowing;
        moreBtn.textContent = expanded ? 'Tampilkan lebih sedikit' : `Lihat semua ${rows.length} ${unit}`;
        moreBtn.setAttribute('aria-expanded', String(expanded));
      }
    }
    apply();

    input?.addEventListener('input', apply);
    buttons.forEach((b) => b.addEventListener('click', () => {
      filter = b.dataset.filter;
      buttons.forEach((x) => x.setAttribute('aria-pressed', String(x === b)));
      apply();
    }));
  }

  wireFilter($('[data-board]'), (row, f) => (f === 'idle' ? row.dataset.isIdle === 'true' : row.dataset.noL1 === 'true'), 'peserta');
  wireFilter($('[data-rooms]'), (row, f) => row.dataset.diff === f, 'room', 20);

  /* ---------- Sortable table ---------- */
  $$('table[data-sortable]').forEach((table) => {
    const tbody = $('tbody', table);
    $$('th[aria-sort] button', table).forEach((btn) => {
      btn.addEventListener('click', () => {
        const th = btn.closest('th');
        const key = btn.dataset.sort;
        const numeric = btn.dataset.type === 'num';
        // Numbers default to high->low (what people look for first); text and rank to A->Z / 1->n.
        const firstDir = numeric && key !== 'position' ? 'descending' : 'ascending';
        const dir = th.getAttribute('aria-sort') === firstDir
          ? (firstDir === 'ascending' ? 'descending' : 'ascending') : firstDir;
        $$('th[aria-sort]', table).forEach((x) => x.setAttribute('aria-sort', 'none'));
        th.setAttribute('aria-sort', dir);
        const sign = dir === 'ascending' ? 1 : -1;
        const val = (r) => (numeric ? Number(r.dataset[key]) : r.dataset[key] || '');
        $$('tr', tbody)
          .sort((a, b) => {
            const x = val(a); const y = val(b);
            return sign * (numeric ? x - y : x.localeCompare(y, 'id'));
          })
          .forEach((r) => tbody.appendChild(r));
      });
    });
  });

  /* ---------- Collapsible grids (show first N, "Lihat semua") ---------- */
  $$('[data-collapsible]').forEach((grid) => {
    const limit = Number(grid.dataset.collapsible);
    const items = [...grid.children];
    if (items.length <= limit) return;
    items.slice(limit).forEach((el) => { el.hidden = true; });
    const wrap = document.createElement('div');
    wrap.className = 'more';
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'btn btn--secondary';
    btn.textContent = `Lihat semua (${items.length})`;
    btn.setAttribute('aria-expanded', 'false');
    btn.addEventListener('click', () => {
      const open = btn.getAttribute('aria-expanded') === 'true';
      items.slice(limit).forEach((el) => { el.hidden = open; });
      btn.setAttribute('aria-expanded', String(!open));
      btn.textContent = open ? `Lihat semua (${items.length})` : 'Tampilkan lebih sedikit';
    });
    wrap.appendChild(btn);
    grid.after(wrap);
  });
})();
