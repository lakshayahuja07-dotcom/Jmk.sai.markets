// JMK Traders app (Sai Markets). Preact + htm, no build step.
import { html, render, useState, useEffect, useRef } from './vendor/preact-htm.js';

/* ---------- helpers ---------- */
const store = {
  get: (k) => { try { return localStorage.getItem(k); } catch (e) { return null; } },
  set: (k, v) => { try { v == null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) { /* private mode */ } },
};
const rs = (paise) => '₹' + Math.round((paise || 0) / 100).toLocaleString('en-IN');
const rsExact = (paise) => '₹' + ((paise || 0) / 100).toLocaleString('en-IN', { maximumFractionDigits: 2 });
const n = (v) => { const x = parseFloat(String(v).replace(/,/g, '')); return isFinite(x) ? x : 0; };
const mic = (it) => (it.micron ? `${+it.micron} mic` : '');
const spec = (it) => [mic(it), `${it.grade} grade`].filter(Boolean).join(' · ');
const fullName = (it) => [it.name, mic(it), it.grade].filter(Boolean).join(' · ');
const tints = ['var(--t1)', 'var(--t2)', 'var(--t3)', 'var(--t4)'];
const tintOf = (s) => tints[[...(s || 'x')].reduce((a, c) => a + c.charCodeAt(0), 0) % 4];
const opId = () => (crypto.randomUUID ? crypto.randomUUID() : String(Date.now()) + Math.random()).slice(0, 36);
const when = (iso) => { const d = new Date(iso); return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'short' }) + ' · ' + d.toLocaleTimeString('en-IN', { hour: 'numeric', minute: '2-digit' }); };
const KIND = { sale: 'Sale', stock_in: 'Stock in', payment_in: 'Payment in', payment_out: 'Payment out', undo: 'Undo' };

let token = store.get('jmk_token');
async function api(path, opts = {}) {
  const headers = { 'Content-Type': 'application/json' };
  if (token) headers.Authorization = 'Bearer ' + token;
  const r = await fetch('/api' + path, { method: opts.method || 'GET', headers, body: opts.body ? JSON.stringify(opts.body) : undefined });
  let data = {};
  try { data = await r.json(); } catch (e) { /* empty */ }
  if (r.status === 401 && token) { token = null; store.set('jmk_token', null); store.set('jmk_me', null); if (!location.hash.startsWith('#/login')) location.hash = '#/login'; }
  if (!r.ok) {
    let msg = data.detail;
    if (Array.isArray(msg)) msg = 'Please check the numbers you typed.';
    if (msg === 'LOCKED') msg = 'App paused. Please contact Sai Markets.';
    throw new Error(msg || 'Something went wrong. Please try again.');
  }
  return data;
}

function photoData(file, max = 1280) {
  return new Promise((ok, no) => {
    const img = new Image();
    img.onload = () => {
      const k = Math.min(1, max / Math.max(img.width, img.height));
      const c = document.createElement('canvas');
      c.width = Math.round(img.width * k); c.height = Math.round(img.height * k);
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      URL.revokeObjectURL(img.src);
      ok(c.toDataURL('image/jpeg', 0.85));
    };
    img.onerror = () => no(new Error('Could not open this photo'));
    img.src = URL.createObjectURL(file);
  });
}

/* ---------- routing ---------- */
function useRoute() {
  const [h, setH] = useState(location.hash || '#/');
  useEffect(() => { const f = () => { setH(location.hash || '#/'); window.scrollTo(0, 0); }; addEventListener('hashchange', f); return () => removeEventListener('hashchange', f); }, []);
  return h.slice(1).split('?')[0] || '/';
}
const go = (p) => { location.hash = '#' + p; };

/* ---------- small pieces ---------- */
const Ico = {
  back: html`<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="m15 18-6-6 6-6"/></svg>`,
  phone: html`<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/></svg>`,
  search: html`<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="#6B645A" stroke-width="2" stroke-linecap="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m20 20-3.5-3.5"/></svg>`,
  out: html`<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M7 17 17 7"/><path d="M8 7h9v9"/></svg>`,
  plus: html`<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14"/><path d="M5 12h14"/></svg>`,
  book: html`<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19V5a2 2 0 0 1 2-2h12v18H6a2 2 0 0 1-2-2z"/><path d="M8 7h6"/><path d="M8 11h6"/></svg>`,
  cash: html`<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="6" width="18" height="12" rx="2"/><circle cx="12" cy="12" r="2.5"/></svg>`,
  cam: html`<svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 8a2 2 0 0 1 2-2h2l2-2h6l2 2h2a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/><circle cx="12" cy="13" r="3.5"/></svg>`,
  mic: html`<svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0"/><path d="M12 18v3"/></svg>`,
  box: html`<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 8 12 3 3 8v8l9 5 9-5z"/><path d="m3 8 9 5 9-5"/><path d="M12 13v8"/></svg>`,
};

function Top({ title, back = '/home', right }) {
  return html`<div class="top"><a class="icon" href=${'#' + back} aria-label="Back">${Ico.back}</a><h1>${title}</h1>${right || ''}</div>`;
}

let toastTimer;
function Toast({ t, onClose }) {
  if (!t) return null;
  return html`<div class="toast" role="status"><span>${t.msg}</span>${t.action ? html`<button onClick=${t.action.run}>${t.action.label}</button>` : ''}</div>`;
}

function Thumb({ it, size }) {
  const st = size ? `width:${size}px;height:${size}px` : '';
  return it.photo
    ? html`<img class="thumb" style=${st} src=${'/api/photo/' + it.photo} alt=${it.name} loading="lazy"/>`
    : html`<div class="thumb" style=${'background:' + tintOf(it.film) + ';' + st} aria-hidden="true">${(it.film || '?').slice(0, 2).toUpperCase()}</div>`;
}

/* ---------- PUBLIC: stock page ---------- */
function Stock() {
  const [data, setData] = useState(null);
  const [shop, setShop] = useState({});
  const [q, setQ] = useState('');
  const [film, setFilm] = useState('All');
  const [picked, setPicked] = useState(() => { try { return JSON.parse(store.get('jmk_pick') || '[]'); } catch (e) { return []; } });
  const [err, setErr] = useState('');
  useEffect(() => {
    api('/stock').then(setData).catch((e) => setErr(e.message));
    api('/shop').then(setShop).catch(() => {});
  }, []);
  useEffect(() => store.set('jmk_pick', JSON.stringify(picked)), [picked]);
  const items = (data?.items || []).filter((it) => (film === 'All' || it.film === film) &&
    (!q || (fullName(it) + ' ' + it.kind + ' ' + (it.note || '')).toLowerCase().includes(q.toLowerCase().trim())));
  const films = ['All', ...new Set((data?.items || []).map((i) => i.film))];
  const wa = shop.whatsapp || shop.phone;
  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]));
  const one = (it) => `Hi ${shop.name || 'JMK'}, I saw this on your stock page. Please share the price:\n• ${fullName(it)} (${it.rolls} rolls)`;
  const many = () => {
    const rows = (data?.items || []).filter((i) => picked.includes(i.id));
    return `Hi ${shop.name || 'JMK'}, please share prices for:\n` + rows.map((it) => `• ${fullName(it)} (${it.rolls} rolls in stock)`).join('\n');
  };
  const waLink = (text) => (wa ? `https://wa.me/${wa}?text=${encodeURIComponent(text)}` : null);
  const pickedNow = picked.filter((id) => (data?.items || []).some((i) => i.id === id));
  return html`<div class="wrap">
    <header class="hero">
      <div class="row between">
        <div class="row">
          <div class="logo" aria-hidden="true">JMK</div>
          <div class="stack" style="gap:0"><span style="font:700 19px var(--head)">${shop.name || 'JMK Traders'}</span>
            <span class="tiny" style="color:var(--dark-muted)">${[shop.tagline || 'Plastic film stocklots', shop.area || 'Alipur, Delhi'].join(' · ')}</span></div>
        </div>
        ${shop.phone ? html`<a class="icon onhero" href=${'tel:+' + shop.phone} aria-label="Call JMK">${Ico.phone}</a>` : ''}
      </div>
      <label class="search">${Ico.search}<input type="search" value=${q} onInput=${(e) => setQ(e.target.value)} placeholder="Search film, micron… e.g. BOPP 20" aria-label="Search stock"/></label>
    </header>
    <div class="pad stack" style="padding-top:16px">
      <div class="chips" role="group" aria-label="Film type">${films.map((f) => html`<button class=${'chip' + (film === f ? ' on' : '')} aria-pressed=${film === f} onClick=${() => setFilm(f)}>${f}</button>`)}</div>
      ${err ? html`<div class="err">${err}</div>` : ''}
      ${data ? html`<p class="small muted" style="margin:0">${items.length} item${items.length === 1 ? '' : 's'} in stock · updated today</p>` : html`<p class="muted">Loading stock…</p>`}
      <div class="list">
        ${items.map((it) => html`<article class=${'item' + (picked.includes(it.id) ? ' picked' : '')}>
          <${Thumb} it=${it}/>
          <div class="grow">
            <h3>${it.name}</h3>
            <span class="small muted">${spec(it)}${it.note ? ' · ' + it.note : ''}</span>
            <span class="small b good">${it.rolls} rolls${it.est_kg ? ` · ~${it.est_kg.toLocaleString('en-IN')} kg` : ''}</span>
            <div class="row" style="margin-top:auto;padding-top:6px">
              <button class="btn ghost sm" onClick=${() => toggle(it.id)} aria-pressed=${picked.includes(it.id)}>${picked.includes(it.id) ? '✓ In my list' : '+ Add to list'}</button>
              ${waLink(one(it)) ? html`<a class="btn wa sm" href=${waLink(one(it))} target="_blank" rel="noopener">Ask price</a>` : ''}
            </div>
          </div>
        </article>`)}
        ${data && !items.length ? html`<div class="empty">Nothing matches. Try another film, or ask us on WhatsApp.</div>` : ''}
      </div>
    </div>
    ${pickedNow.length && waLink(many()) ? html`<div class="sticky"><a class="btn wa full" href=${waLink(many())} target="_blank" rel="noopener">Send my list on WhatsApp · ${pickedNow.length} item${pickedNow.length > 1 ? 's' : ''}</a></div>` : ''}
    <footer class="foot">Prices on request. Stock changes daily.<br/><a href="#/login">Staff sign in</a> · Made by <a href="https://sai.markets" target="_blank" rel="noopener">SAImarkets</a></footer>
  </div>`;
}

/* ---------- LOGIN ---------- */
function Login({ onIn }) {
  const [staff, setStaff] = useState([]);
  const [taps, setTaps] = useState(0);
  const [who, setWho] = useState(null);
  const [pin, setPin] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  useEffect(() => { api('/staff/public').then((d) => setStaff(d.staff)).catch((e) => setErr(e.message)); }, []);
  const cards = taps >= 5 ? [...staff, { id: 'ghost', name: 'Sai Markets' }] : staff;
  const signIn = async (p) => {
    setBusy(true);
    try {
      const r = await api('/auth/login', { method: 'POST', body: { staff_id: who.id, pin: p } });
      token = r.token; store.set('jmk_token', r.token); store.set('jmk_me', JSON.stringify(r.me)); onIn(r.me); go('/home');
    } catch (e) { setErr(e.message); setPin(''); }
    setBusy(false);
  };
  // 4-digit PINs press "Sign in"; 6-digit PINs sign in by themselves (never a wrong guess at 4 digits)
  const press = (d) => {
    if (busy) return;
    const p = d === 'del' ? pin.slice(0, -1) : (pin + d).slice(0, 6);
    setPin(p); setErr('');
    if (p.length === 6) signIn(p);
  };
  return html`<div class="wrap pad stack">
    <div class="row" style="margin-top:20px"><button class="logo" onClick=${() => setTaps(taps + 1)} aria-label="JMK">JMK</button><h1>Sign in</h1></div>
    ${!who ? html`<div class="list">${cards.map((s) => html`<button class="line" style="text-align:left" onClick=${() => { setWho(s); setPin(''); }}>
        <div class="avatar" style=${'background:' + tintOf(s.name)}>${s.name[0]}</div><div class="grow"><span class="b">${s.name}</span><span class="tiny muted">${s.role || ''}</span></div></button>`)}</div>
      <a class="btn ghost" href="#/">Back to stock page</a>` : html`
      <p class="muted" style="margin:0">PIN for <b>${who.name}</b></p>
      <div class="dots" aria-label=${pin.length + ' digits typed'}>${[0, 1, 2, 3].map((i) => html`<i class=${pin.length > i ? 'on' : ''}></i>`)}${pin.length > 4 ? [4, 5].map((i) => html`<i class=${pin.length > i ? 'on' : ''}></i>`) : ''}</div>
      ${err ? html`<div class="err">${err}</div>` : ''}
      <div class="pinpad">${['1', '2', '3', '4', '5', '6', '7', '8', '9', '', '0', 'del'].map((d) => d === '' ? html`<span></span>` :
        html`<button onClick=${() => press(d)} aria-label=${d === 'del' ? 'Delete' : d}>${d === 'del' ? '⌫' : d}</button>`)}</div>
      <button class="btn" disabled=${pin.length !== 4 || busy} onClick=${() => signIn(pin)}>${busy ? 'Checking…' : 'Sign in'}</button>
      <button class="btn ghost" onClick=${() => setWho(null)}>Someone else</button>`}
  </div>`;
}

/* ---------- OWNER: home ---------- */
function Home({ me, toast }) {
  const [s, setS] = useState(null);
  const [err, setErr] = useState('');
  const load = () => api('/summary').then(setS).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);
  const undo = async (e) => {
    if (!confirmUndo(e)) return;
    try { await api(`/entries/${e.id}/undo`, { method: 'POST' }); toast('Undone. Stock and khata are back.'); load(); } catch (x) { toast(x.message); }
  };
  const d = new Date();
  return html`<div class="wrap pad stack">
    <div class="row between">
      <div class="stack" style="gap:0"><span class="small muted">${d.toLocaleDateString('en-IN', { weekday: 'short', day: 'numeric', month: 'short' })}</span><h1>Namaste, ${(me?.name || '').split(' ')[0]}</h1></div>
      <a class="logo" href="#/more" aria-label="More options" style="text-decoration:none">JMK</a>
    </div>
    ${err ? html`<div class="err">${err}</div>` : ''}
    <a class="askbar" href="#/ai">${Ico.mic}<span>${(me?.lang || 'en') === 'en' ? 'Say it: “Sharma 250kg 95 credit”' : 'Boliye: “Sharma 250kg 95 udhaar”'}</span></a>
    <div class="dark stack" style="gap:4px"><span class="small muted">Sold today</span><span class="big num">${s ? rs(s.sold_today) : '…'}</span>
      <span class="small" style="color:var(--mint)">${s ? `${s.sales_today} sale${s.sales_today === 1 ? '' : 's'}${s.kg_today ? ` · ${s.kg_today.toLocaleString('en-IN')} kg out` : ''} · ${s.rolls_in_stock} rolls in stock` : ''}</span></div>
    <div class="grid2">
      <a class="card stack" style="gap:2px;text-decoration:none;color:inherit" href="#/khata/buyer"><span class="tiny muted">Lena hai (to receive)</span><span class="mid good num">${s ? rs(s.lena) : '…'}</span><span class="tiny muted">${s ? s.buyers_owing + (s.buyers_owing === 1 ? ' buyer' : ' buyers') : ''}</span></a>
      <a class="card stack" style="gap:2px;text-decoration:none;color:inherit" href="#/khata/supplier"><span class="tiny muted">Dena hai (to pay)</span><span class="mid bad num">${s ? rs(s.dena) : '…'}</span><span class="tiny muted">${s ? s.suppliers_owed + (s.suppliers_owed === 1 ? ' supplier' : ' suppliers') : ''}</span></a>
    </div>
    <div class="grid2">
      <a class="tile c" href="#/sale">${Ico.out}Record a sale</a>
      <a class="tile m" href="#/add">${Ico.plus}Add stock</a>
      <a class="tile g" href="#/khata/buyer">${Ico.book}Khata</a>
      <a class="tile w" href="#/pay">${Ico.cash}Payment in / out</a>
    </div>
    <a class="btn ghost" href="#/items">${Ico.box} All stock items</a>
    <h3>Today</h3>
    <div class="list">${(s?.recent || []).map((e) => html`<${EntryLine} e=${e} onUndo=${undo}/>`)}
      ${s && !s.recent.length ? html`<div class="empty">Nothing yet today. Record your first sale.</div>` : ''}</div>
  </div>`;
}

function confirmUndo(e) {
  return window.confirm(`Undo this ${KIND[e.kind].toLowerCase()} of ${rs(e.amount)}? Stock and khata go back to how they were.`);
}

function EntryLine({ e, onUndo }) {
  const sub = e.kind === 'sale' ? `${e.item_name} · ${e.unit === 'kg' ? `${e.kg} kg` : `${e.rolls} rolls`}${e.rolls && e.unit === 'kg' ? ` (${e.rolls} rolls)` : ''} · ${e.pay === 'credit' ? 'udhaar' : 'cash'}`
    : e.kind === 'stock_in' ? `${e.item_name} · +${e.rolls} rolls${e.amount ? ' · ' + (e.pay === 'credit' ? 'udhaar' : 'paid') : ''}`
    : e.kind === 'undo' ? e.note : `${e.mode || ''}${e.note ? ' · ' + e.note : ''}`;
  const head = `${KIND[e.kind]}${e.party_name ? ' · ' + e.party_name : ''}`;
  return html`<div class=${'line' + (e.reversed ? ' undone' : '')}>
    <div class="grow"><span class="b">${head}</span><span class="tiny muted">${sub}</span><span class="tiny muted">${when(e.at)}${e.by_name ? ' · ' + e.by_name.split(' ')[0] : ''}${e.reversed ? ' · undone' : ''}</span></div>
    <div class="stack" style="gap:4px;align-items:flex-end"><span class="b num">${e.amount ? rs(e.amount) : ''}</span>
      ${onUndo && !e.reversed && e.kind !== 'undo' ? html`<button class="btn ghost sm" style="min-height:34px" onClick=${() => onUndo(e)}>Undo</button>` : ''}</div>
  </div>`;
}

/* ---------- OWNER: item picker ---------- */
function ItemPicker({ items, value, onPick }) {
  const [q, setQ] = useState('');
  const list = items.filter((it) => !q || fullName(it).toLowerCase().includes(q.toLowerCase().trim()));
  if (value) {
    const it = items.find((i) => i.id === value);
    if (it) return html`<button class="line" style="text-align:left;border-color:var(--ink)" onClick=${() => onPick(null)}>
      <${Thumb} it=${it} size=${44}/><div class="grow"><span class="b">${fullName(it)}</span><span class="tiny muted">In stock: ${it.rolls} rolls${it.est_kg ? ` · ~${it.est_kg} kg` : ''}</span></div><span class="tiny muted">Change</span></button>`;
  }
  return html`<div class="stack" style="gap:8px">
    <input class="in" type="search" placeholder="Search item… e.g. BOPP 20" value=${q} onInput=${(e) => setQ(e.target.value)} aria-label="Search item"/>
    <div class="list" style="gap:8px;max-height:320px;overflow:auto">${list.map((it) => html`<button class="line" style="text-align:left" onClick=${() => onPick(it.id)}>
      <${Thumb} it=${it} size=${40}/><div class="grow"><span class="b">${fullName(it)}</span><span class="tiny muted">${it.rolls} rolls in stock</span></div></button>`)}
      ${!list.length ? html`<div class="empty">No item found. Add it with "Add stock" first.</div>` : ''}</div></div>`;
}

/* ---------- OWNER: record a sale ---------- */
function Sale({ toast }) {
  const [items, setItems] = useState([]);
  const [buyers, setBuyers] = useState([]);
  const [f, setF] = useState({ item_id: null, unit: 'kg', rolls: '', kg: '', rate: '', party: '', phone: '', pay: 'credit', note: '' });
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const op = useRef(opId());
  useEffect(() => {
    api('/items').then((d) => setItems(d.items)).catch((e) => setErr(e.message));
    api('/parties?kind=buyer').then((d) => setBuyers(d.parties)).catch(() => {});
  }, []);
  const set = (k) => (e) => setF({ ...f, [k]: e.target ? e.target.value : e });
  const it = items.find((i) => i.id === f.item_id);
  const qty = f.unit === 'kg' ? n(f.kg) : n(f.rolls);
  const total = Math.round(qty * n(f.rate) * 100);
  const after = it ? it.rolls - n(f.rolls) : 0;
  const buyer = buyers.find((b) => b.name.toLowerCase() === f.party.trim().toLowerCase());
  const save = async () => {
    setErr(''); setBusy(true);
    try {
      await api('/sales', { method: 'POST', body: { item_id: f.item_id, unit: f.unit, rolls: Math.round(n(f.rolls)), kg: n(f.kg), rate: n(f.rate), party: f.party, phone: f.phone.replace(/\D/g, ''), pay: f.pay, note: f.note, op: op.current } });
      toast(`Sale saved · ${rs(total)}`); go('/home');
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const ok = it && qty > 0 && n(f.rate) > 0 && (f.pay === 'cash' || f.party.trim());
  return html`<div class="wrap">
    <${Top} title="Record a sale"/>
    <div class="pad stack">
      <span class="small b muted">Item</span>
      <${ItemPicker} items=${items} value=${f.item_id} onPick=${(id) => setF({ ...f, item_id: id })}/>
      <div class="stack" style="gap:6px"><span class="small b muted">Rate is per</span>
        <div class="seg" role="group" aria-label="Rate per"><button class=${f.unit === 'kg' ? 'on' : ''} onClick=${() => setF({ ...f, unit: 'kg' })}>Kg</button><button class=${f.unit === 'roll' ? 'on' : ''} onClick=${() => setF({ ...f, unit: 'roll' })}>Roll / bale</button></div></div>
      <div class="grid2">
        <label class="f">Rolls${f.unit === 'kg' ? ' (count)' : ''}<input class="in" inputmode="numeric" value=${f.rolls} onInput=${set('rolls')} placeholder="0"/></label>
        <label class="f">Kanta weight (kg)${f.unit === 'roll' ? ' · optional' : ''}<input class="in" inputmode="decimal" value=${f.kg} onInput=${set('kg')} placeholder="0"/></label>
        <label class="f">Rate ₹ / ${f.unit === 'kg' ? 'kg' : 'roll'}<input class="in" inputmode="decimal" value=${f.rate} onInput=${set('rate')} placeholder="0"/></label>
        <label class="f">Buyer<input class="in" list="buyers" value=${f.party} onInput=${set('party')} placeholder="Name" autocomplete="off"/></label>
      </div>
      <datalist id="buyers">${buyers.map((b) => html`<option value=${b.name}/>`)}</datalist>
      ${f.party && !buyer ? html`<label class="f">New buyer's WhatsApp number (optional)<input class="in" inputmode="tel" value=${f.phone} onInput=${set('phone')} placeholder="98xxxxxxxx"/></label>` : ''}
      <div class="seg" role="group" aria-label="Payment"><button class=${f.pay === 'cash' ? 'on' : ''} onClick=${() => setF({ ...f, pay: 'cash' })}>Cash / paid</button><button class=${f.pay === 'credit' ? 'on' : ''} onClick=${() => setF({ ...f, pay: 'credit' })}>Udhaar (credit)</button></div>
      <div class="preview">
        <div class="row between"><span class="muted">Total</span><span class="big num" style="font-size:28px">${rsExact(total)}</span></div>
        ${it ? html`<div class="row between small"><span class="muted">Stock after</span><span class=${'b ' + (after < 0 ? 'bad' : '')}>${after} rolls${after < 0 ? ' · more than in stock!' : ''}</span></div>` : ''}
        ${f.pay === 'credit' && f.party ? html`<div class="row between small"><span class="muted">${f.party} khata</span><span class="b good">+${rs(total)} lena${buyer ? ` (now ${rs(buyer.balance + total)})` : ''}</span></div>` : ''}
      </div>
      <details><summary>Add a note</summary><input class="in" value=${f.note} onInput=${set('note')} placeholder="e.g. vehicle no., bill no."/></details>
      ${err ? html`<div class="err">${err}</div>` : ''}
    </div>
    <div class="sticky"><button class="btn full" disabled=${!ok || busy} onClick=${save}>${busy ? 'Saving…' : 'Save sale'}</button>
      <p class="tiny muted" style="text-align:center;margin:6px 0 0">Saves stock, sale and khata together. Undo anytime.</p></div>
  </div>`;
}

/* ---------- OWNER: add stock ---------- */
const FILMS = ['BOPP', 'Polyester', 'LDPE', 'CPP', 'Nylon', 'Metallised', 'PVC', 'HDPE', 'Other'];
function AddStock({ toast }) {
  const [items, setItems] = useState([]);
  const [suppliers, setSuppliers] = useState([]);
  const [f, setF] = useState({ film: 'BOPP', kind: '', micron: '', grade: 'A', rolls: 1, supplier: '', amount: '', pay: 'cash', note: '' });
  const [photo, setPhoto] = useState(null);
  const [ai, setAi] = useState('');
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const op = useRef(opId());
  const fileRef = useRef(null);
  useEffect(() => {
    api('/items').then((d) => setItems(d.items)).catch((e) => setErr(e.message));
    api('/parties?kind=supplier').then((d) => setSuppliers(d.parties)).catch(() => {});
  }, []);
  const set = (k) => (e) => setF({ ...f, [k]: e.target ? e.target.value : e });
  const key = (x) => [x.film.trim().toLowerCase(), (x.kind || '').trim().toLowerCase(), String(+n(x.micron)), x.grade].join('|');
  const existing = items.find((it) => key(it) === key(f));
  const pickPhoto = async (e) => {
    const file = e.target.files && e.target.files[0];
    if (!file) return;
    setErr('');
    try {
      const d = await photoData(file);
      setPhoto(d); setAi('Reading the photo…');
      try {
        const r = await api('/ai/read-roll', { method: 'POST', body: { photo: d } });
        setF((o) => ({ ...o, film: r.film, kind: r.kind || o.kind, micron: r.micron ? String(r.micron) : o.micron, grade: r.grade }));
        setAi(`AI read it (${r.confidence.toLowerCase()} confidence). Please check.${r.note ? ' Label: ' + r.note : ''}`);
      } catch (x) { setAi(x.message); }
    } catch (x) { setErr(x.message); }
  };
  const save = async () => {
    setErr(''); setBusy(true);
    try {
      const r = await api('/stock-in', { method: 'POST', body: {
        item: { film: f.film, kind: f.kind, micron: n(f.micron), grade: f.grade }, rolls: Math.round(n(f.rolls)),
        supplier: f.supplier, amount: n(f.amount), pay: f.pay, note: f.note, photo, op: op.current } });
      toast(`Added ${f.rolls} rolls · now ${r.item.rolls} in stock`); go('/home');
    } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  const ok = f.film && n(f.rolls) > 0 && (f.pay === 'cash' || (f.supplier.trim() && n(f.amount) > 0));
  return html`<div class="wrap">
    <${Top} title="Add stock"/>
    <div class="pad stack">
      <input type="file" accept="image/*" capture="environment" ref=${fileRef} onChange=${pickPhoto} hidden/>
      <button class="photo" onClick=${() => fileRef.current.click()}>${photo ? html`<img src=${photo} alt="Roll photo"/>` : Ico.cam}
        ${photo ? 'Change photo' : 'Photo of the roll'}<span class="tiny muted" style="font-weight:500">${ai || 'AI fills film, micron and grade. You check.'}</span></button>
      <div class="stack" style="gap:6px"><span class="small b muted">Film</span>
        <div class="chips wrapit" role="group" aria-label="Film">${FILMS.map((x) => html`<button class=${'chip' + (f.film === x ? ' on' : '')} aria-pressed=${f.film === x} onClick=${() => setF({ ...f, film: x })}>${x}</button>`)}</div></div>
      <div class="grid2">
        <label class="f">Type (optional)<input class="in" value=${f.kind} onInput=${set('kind')} placeholder="Plain, printed…" list="kinds"/></label>
        <label class="f">Micron<input class="in" inputmode="decimal" value=${f.micron} onInput=${set('micron')} placeholder="e.g. 20"/></label>
      </div>
      <datalist id="kinds">${['Plain', 'Printed', 'Metallised', 'Silicone coated', 'Laminate', 'Yellow (lobhan)'].map((k) => html`<option value=${k}/>`)}</datalist>
      <div class="stack" style="gap:6px"><span class="small b muted">Grade</span>
        <div class="seg grade" role="group" aria-label="Grade">${[['A', 'A · usable'], ['B', 'B · process'], ['C', 'C · scrap']].map(([g, l]) => html`<button class=${f.grade === g ? 'on' : ''} onClick=${() => setF({ ...f, grade: g })}>${l}</button>`)}</div></div>
      <label class="f">Rolls added<div class="stepper"><button onClick=${() => setF({ ...f, rolls: Math.max(1, n(f.rolls) - 1) })} aria-label="One less">−</button>
        <input class="in big" inputmode="numeric" value=${f.rolls} onInput=${set('rolls')}/><button onClick=${() => setF({ ...f, rolls: n(f.rolls) + 1 })} aria-label="One more">+</button></div></label>
      <div class="card row between small"><span class="muted">${existing ? 'Already in stock' : 'New item'}</span><span class="b">${existing ? `${existing.rolls} → ${existing.rolls + Math.round(n(f.rolls))} rolls` : `${Math.round(n(f.rolls))} rolls`}</span></div>
      <details><summary>Bought from a supplier? (for dena khata)</summary><div class="stack" style="padding-top:8px">
        <label class="f">Supplier<input class="in" list="sups" value=${f.supplier} onInput=${set('supplier')} placeholder="Name" autocomplete="off"/></label>
        <datalist id="sups">${suppliers.map((s) => html`<option value=${s.name}/>`)}</datalist>
        <label class="f">Total amount ₹<input class="in" inputmode="decimal" value=${f.amount} onInput=${set('amount')} placeholder="0"/></label>
        <div class="seg" role="group" aria-label="Payment"><button class=${f.pay === 'cash' ? 'on' : ''} onClick=${() => setF({ ...f, pay: 'cash' })}>Paid</button><button class=${f.pay === 'credit' ? 'on' : ''} onClick=${() => setF({ ...f, pay: 'credit' })}>Udhaar (to pay)</button></div>
      </div></details>
      ${err ? html`<div class="err">${err}</div>` : ''}
    </div>
    <div class="sticky"><button class="btn mango full" disabled=${!ok || busy} onClick=${save}>${busy ? 'Saving…' : 'Add to stock'}</button></div>
  </div>`;
}

/* ---------- OWNER: khata ---------- */
function Khata({ kind }) {
  const [d, setD] = useState(null);
  const [q, setQ] = useState('');
  const [err, setErr] = useState('');
  useEffect(() => { setD(null); api('/parties?kind=' + kind).then(setD).catch((e) => setErr(e.message)); }, [kind]);
  const list = (d?.parties || []).filter((p) => !q || p.name.toLowerCase().includes(q.toLowerCase()));
  return html`<div class="wrap">
    <${Top} title="Khata"/>
    <div class="pad stack">
      <div class="seg" role="group" aria-label="Khata type"><button class=${kind === 'buyer' ? 'on' : ''} onClick=${() => go('/khata/buyer')}>Buyers · lena</button><button class=${kind === 'supplier' ? 'on' : ''} onClick=${() => go('/khata/supplier')}>Suppliers · dena</button></div>
      <div class="row between"><span class="muted small">Total ${kind === 'buyer' ? 'to receive' : 'to pay'}</span><span class=${'mid num ' + (kind === 'buyer' ? 'good' : 'bad')}>${d ? rs(d.total) : '…'}</span></div>
      ${(d?.parties || []).length > 6 ? html`<input class="in" type="search" placeholder="Search name" value=${q} onInput=${(e) => setQ(e.target.value)} aria-label="Search name"/>` : ''}
      ${err ? html`<div class="err">${err}</div>` : ''}
      <div class="list" style="gap:8px">${list.map((p) => html`<a class="line" style="text-decoration:none;color:inherit" href=${'#/party/' + p.id}>
        <div class="avatar" style=${'background:' + tintOf(p.name)}>${p.name[0]}</div>
        <div class="grow"><span class="b">${p.name}</span><span class="tiny muted">${p.last_at ? 'Last entry ' + when(p.last_at).split(' · ')[0] : ''}</span></div>
        <span class=${'b num ' + (p.balance > 0 ? (kind === 'buyer' ? 'good' : 'bad') : 'muted')}>${p.balance ? rs(p.balance) : 'Settled'}</span></a>`)}
        ${d && !list.length ? html`<div class="empty">No ${kind === 'buyer' ? 'buyers' : 'suppliers'} yet. They appear when you record an udhaar ${kind === 'buyer' ? 'sale' : 'purchase'}.</div>` : ''}</div>
    </div>
    <div class="sticky"><a class="btn mint full" href=${'#/pay?' + kind}>${kind === 'buyer' ? 'Payment in' : 'Payment out'}</a></div>
  </div>`;
}

function Party({ id, toast, shop }) {
  const [d, setD] = useState(null);
  const [err, setErr] = useState('');
  const load = () => api('/parties/' + id).then(setD).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, [id]);
  const undo = async (e) => {
    if (!confirmUndo(e)) return;
    try { await api(`/entries/${e.id}/undo`, { method: 'POST' }); toast('Undone.'); load(); } catch (x) { toast(x.message); }
  };
  const p = d?.party;
  const remind = p && p.phone && p.balance > 0 ? `https://wa.me/${p.phone.length === 10 ? '91' + p.phone : p.phone}?text=${encodeURIComponent(`Namaste ${p.name} ji, ${shop.name || 'JMK Traders'} se. Aapka ${rs(p.balance)} baaki hai. Kripya jab sahi lage bhej dijiye. Dhanyavaad.`)}` : null;
  return html`<div class="wrap">
    <${Top} title=${p ? p.name : 'Khata'} back=${'/khata/' + (p ? p.kind : 'buyer')}/>
    <div class="pad stack">
      ${err ? html`<div class="err">${err}</div>` : ''}
      ${p ? html`<div class="dark stack" style="gap:4px"><span class="small muted">${p.kind === 'buyer' ? 'Lena hai' : 'Dena hai'}</span><span class="big num">${rs(p.balance)}</span>
        <span class="small muted">${p.phone ? '+' + (p.phone.length === 10 ? '91' + p.phone : p.phone) : 'No number saved'}</span></div>
      <div class="grid2">${remind ? html`<a class="btn wa" href=${remind} target="_blank" rel="noopener">Send reminder</a>` : ''}
        <a class="btn ghost" href=${'#/pay?' + p.kind + '&' + encodeURIComponent(p.name)}>${p.kind === 'buyer' ? 'Payment in' : 'Payment out'}</a></div>
      <h3>History</h3>
      <div class="list" style="gap:8px">${d.entries.map((e) => html`<${EntryLine} e=${e} onUndo=${undo}/>`)}</div>` : html`<p class="muted">Loading…</p>`}
    </div>
  </div>`;
}

/* ---------- OWNER: payment in / out ---------- */
function Pay({ toast }) {
  const qs = (location.hash.split('?')[1] || '').split('&');
  const [f, setF] = useState({ kind: qs[0] === 'supplier' ? 'supplier' : 'buyer', party: decodeURIComponent(qs[1] || ''), amount: '', mode: 'cash', note: '' });
  const [parties, setParties] = useState([]);
  const [err, setErr] = useState('');
  const [busy, setBusy] = useState(false);
  const op = useRef(opId());
  useEffect(() => { api('/parties?kind=' + f.kind).then((d) => setParties(d.parties)).catch(() => {}); }, [f.kind]);
  const set = (k) => (e) => setF({ ...f, [k]: e.target.value });
  const p = parties.find((x) => x.name.toLowerCase() === f.party.trim().toLowerCase());
  const save = async () => {
    setErr(''); setBusy(true);
    try { await api('/payments', { method: 'POST', body: { ...f, amount: n(f.amount), op: op.current } }); toast(`Payment saved · ${rs(n(f.amount) * 100)}`); history.back(); } catch (e) { setErr(e.message); }
    setBusy(false);
  };
  return html`<div class="wrap">
    <${Top} title="Payment"/>
    <div class="pad stack">
      <div class="seg" role="group" aria-label="Direction"><button class=${f.kind === 'buyer' ? 'on' : ''} onClick=${() => setF({ ...f, kind: 'buyer' })}>In · from buyer</button><button class=${f.kind === 'supplier' ? 'on' : ''} onClick=${() => setF({ ...f, kind: 'supplier' })}>Out · to supplier</button></div>
      <label class="f">${f.kind === 'buyer' ? 'Buyer' : 'Supplier'}<input class="in" list="pp" value=${f.party} onInput=${set('party')} placeholder="Name" autocomplete="off"/></label>
      <datalist id="pp">${parties.map((x) => html`<option value=${x.name}/>`)}</datalist>
      ${p ? html`<p class="small muted" style="margin:0">${f.kind === 'buyer' ? 'Lena hai' : 'Dena hai'}: <b>${rs(p.balance)}</b></p>` : ''}
      <label class="f">Amount ₹<input class="in big" inputmode="decimal" value=${f.amount} onInput=${set('amount')} placeholder="0"/></label>
      <div class="seg" role="group" aria-label="Mode">${['cash', 'upi', 'bank', 'cheque'].map((m) => html`<button class=${f.mode === m ? 'on' : ''} onClick=${() => setF({ ...f, mode: m })}>${m.toUpperCase() === 'UPI' ? 'UPI' : m[0].toUpperCase() + m.slice(1)}</button>`)}</div>
      <label class="f">Note (optional)<input class="in" value=${f.note} onInput=${set('note')} placeholder="e.g. cheque no."/></label>
      ${p && n(f.amount) ? html`<div class="preview"><div class="row between small"><span class="muted">After this</span><span class="b">${rs(p.balance - Math.round(n(f.amount) * 100))}</span></div></div>` : ''}
      ${err ? html`<div class="err">${err}</div>` : ''}
    </div>
    <div class="sticky"><button class="btn mint full" disabled=${busy || !f.party.trim() || n(f.amount) <= 0} onClick=${save}>${busy ? 'Saving…' : 'Save payment'}</button></div>
  </div>`;
}

/* ---------- OWNER: all items ---------- */
function Items({ toast }) {
  const [d, setD] = useState(null);
  const [q, setQ] = useState('');
  const [err, setErr] = useState('');
  const load = () => api('/items').then(setD).catch((e) => setErr(e.message));
  useEffect(() => { load(); }, []);
  const patch = async (it, body, msg) => { try { await api('/items/' + it.id, { method: 'PATCH', body }); toast(msg); load(); } catch (e) { toast(e.message); } };
  const photo = (it) => {
    const i = document.createElement('input'); i.type = 'file'; i.accept = 'image/*';
    i.onchange = async () => { if (i.files[0]) { try { patch(it, { photo: await photoData(i.files[0]) }, 'Photo saved'); } catch (e) { toast(e.message); } } };
    i.click();
  };
  const list = (d?.items || []).filter((it) => !q || fullName(it).toLowerCase().includes(q.toLowerCase()));
  return html`<div class="wrap">
    <${Top} title="Stock items"/>
    <div class="pad stack">
      <input class="in" type="search" placeholder="Search item" value=${q} onInput=${(e) => setQ(e.target.value)} aria-label="Search item"/>
      ${err ? html`<div class="err">${err}</div>` : ''}
      <div class="list">${list.map((it) => html`<div class="item">
        <button style="border:0;padding:0;background:none" onClick=${() => photo(it)} aria-label="Change photo"><${Thumb} it=${it}/></button>
        <div class="grow"><h3>${it.name}</h3><span class="small muted">${spec(it)}</span>
          <span class="small b">${it.rolls} rolls${it.est_kg ? ` · ~${it.est_kg} kg` : ''}${it.avg_kg ? html` <span class="muted">(avg ${it.avg_kg} kg/roll)</span>` : ''}</span>
          <div class="row" style="padding-top:6px"><button class="btn ghost sm" onClick=${() => patch(it, { visible: !it.visible }, it.visible ? 'Hidden from buyers' : 'Shown to buyers')}>${it.visible ? 'Shown to buyers' : 'Hidden'}</button></div></div></div>`)}
        ${d && !list.length ? html`<div class="empty">No items yet. Use "Add stock".</div>` : ''}</div>
    </div>
  </div>`;
}

/* ---------- More (team + super admin) ---------- */
function More({ me, onOut, toast }) {
  const [shop, setShop] = useState(null);
  const [err, setErr] = useState('');
  const isSuper = me?.role === 'Sai Markets Super Admin';
  const [team, setTeam] = useState([]);
  const [help, setHelp] = useState({ name: '', wa_phone: '' });
  const [dict, setDict] = useState(null);
  const loadTeam = () => api('/staff').then((d) => setTeam(d.staff)).catch(() => {});
  useEffect(() => { api('/shop').then(setShop).catch(() => {}); loadTeam(); api('/ai/dictionary').then((d) => setDict(d.text)).catch(() => {}); }, []);
  const addHelper = async () => { try { await api('/staff/helper', { method: 'POST', body: { name: help.name, wa_phone: help.wa_phone.replace(/\D/g, '') } }); setHelp({ name: '', wa_phone: '' }); toast('Worker added. Their WhatsApp can now ask what a roll is.'); loadTeam(); } catch (e) { toast(e.message); } };
  const off = async (p) => { try { await api('/staff/' + p.id, { method: 'PATCH', body: { active: !p.active } }); loadTeam(); } catch (e) { toast(e.message); } };
  const linkWa = async (p) => { const v = window.prompt('WhatsApp number for ' + p.name + ' (with 91)', p.wa_phone || ''); if (v == null) return; try { await api('/staff/' + p.id, { method: 'PATCH', body: { wa_phone: v.replace(/\D/g, '') } }); toast('WhatsApp linked'); loadTeam(); } catch (e) { toast(e.message); } };
  const saveDict = async () => { try { await api('/ai/dictionary', { method: 'PUT', body: { text: dict } }); toast('Shop words saved'); } catch (e) { toast(e.message); } };
  const save = async () => { setErr(''); try { await api('/admin/shop', { method: 'PUT', body: shop }); toast('Shop details saved'); } catch (e) { setErr(e.message); } };
  const set = (k) => (e) => setShop({ ...shop, [k]: k === 'phone' || k === 'whatsapp' ? e.target.value.replace(/\D/g, '') : e.target.value });
  return html`<div class="wrap">
    <${Top} title="More"/>
    <div class="pad stack">
      <p class="muted" style="margin:0">Signed in as <b>${me?.name}</b></p>
      <a class="btn ghost" href="#/">Open the buyers' stock page</a>
      ${isSuper && shop ? html`<div class="card stack"><h3>Shop details (Sai Markets only)</h3>
        <label class="f">Name<input class="in" value=${shop.name} onInput=${set('name')}/></label>
        <label class="f">Line under name<input class="in" value=${shop.tagline} onInput=${set('tagline')}/></label>
        <label class="f">Area<input class="in" value=${shop.area} onInput=${set('area')}/></label>
        <label class="f">Call number (with 91)<input class="in" inputmode="tel" value=${shop.phone} onInput=${set('phone')} placeholder="9198xxxxxxxx"/></label>
        <label class="f">WhatsApp number for buyers (with 91)<input class="in" inputmode="tel" value=${shop.whatsapp} onInput=${set('whatsapp')} placeholder="9198xxxxxxxx"/></label>
        ${err ? html`<div class="err">${err}</div>` : ''}<button class="btn" onClick=${save}>Save shop details</button></div>` : ''}
      <div class="card stack"><h3>Godown workers (WhatsApp)</h3>
        <p class="small muted" style="margin:0">They can send a roll photo to the JMK bot and get told what material it is. They can't see or change stock or money.</p>
        ${team.filter((p) => p.role === 'Labour').map((p) => html`<div class="row between"><span>${p.name} · ${p.wa_phone}</span><button class="btn ghost sm" onClick=${() => off(p)}>${p.active ? 'Switch off' : 'Switch on'}</button></div>`)}
        <div class="grid2"><input class="in" placeholder="Name" value=${help.name} onInput=${(e) => setHelp({ ...help, name: e.target.value })} aria-label="Worker name"/>
          <input class="in" inputmode="tel" placeholder="98xxxxxxxx" value=${help.wa_phone} onInput=${(e) => setHelp({ ...help, wa_phone: e.target.value })} aria-label="Worker WhatsApp number"/></div>
        <button class="btn ghost" disabled=${!help.name.trim() || help.wa_phone.replace(/\D/g, '').length < 10} onClick=${addHelper}>Add worker</button></div>
      ${isSuper ? html`<div class="card stack"><h3>WhatsApp bot access (Sai Markets only)</h3>
        ${team.filter((p) => p.role !== 'Labour').map((p) => html`<div class="row between"><span>${p.name}<br/><span class="tiny muted">${p.wa_phone ? '+' + p.wa_phone : 'not linked'}</span></span><button class="btn ghost sm" onClick=${() => linkWa(p)}>${p.wa_phone ? 'Change' : 'Link number'}</button></div>`)}</div>` : ''}
      ${dict != null ? html`<div class="card stack"><h3>Shop words for the AI</h3>
        <p class="small muted" style="margin:0">One per line, like "lobhan = yellow LDPE film". The AI reads these every time.</p>
        <textarea class="in" style="min-height:140px;padding:12px;font-size:15px;font-weight:500" value=${dict} onInput=${(e) => setDict(e.target.value)} aria-label="Shop words"></textarea>
        <button class="btn ghost" onClick=${saveDict}>Save shop words</button></div>` : ''}
      <button class="btn ghost" onClick=${onOut}>Sign out</button>
      <p class="tiny muted" style="text-align:center">JMK Traders app · made by SAImarkets</p>
    </div>
  </div>`;
}

/* ---------- voice: record WAV in the browser (works on Android and iPhone) ---------- */
async function startRec() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true } });
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  const src = ctx.createMediaStreamSource(stream);
  const proc = ctx.createScriptProcessor(4096, 1, 1);
  const chunks = [];
  proc.onaudioprocess = (e) => chunks.push(new Float32Array(e.inputBuffer.getChannelData(0)));
  src.connect(proc); proc.connect(ctx.destination);
  return {
    started: Date.now(),
    async stop() {
      proc.disconnect(); src.disconnect(); stream.getTracks().forEach((t) => t.stop());
      const rate = ctx.sampleRate; await ctx.close();
      let len = 0; chunks.forEach((c) => { len += c.length; });
      const all = new Float32Array(len); let o = 0; chunks.forEach((c) => { all.set(c, o); o += c.length; });
      const target = 16000, step = rate / target, out = new Int16Array(Math.floor(all.length / step));
      for (let i = 0; i < out.length; i++) { const v = Math.max(-1, Math.min(1, all[Math.floor(i * step)] || 0)); out[i] = v < 0 ? v * 0x8000 : v * 0x7fff; }
      const buf = new ArrayBuffer(44 + out.length * 2), dv = new DataView(buf);
      const w = (p, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(p + i, s.charCodeAt(i)); };
      w(0, 'RIFF'); dv.setUint32(4, 36 + out.length * 2, true); w(8, 'WAVE'); w(12, 'fmt '); dv.setUint32(16, 16, true); dv.setUint16(20, 1, true);
      dv.setUint16(22, 1, true); dv.setUint32(24, target, true); dv.setUint32(28, target * 2, true); dv.setUint16(32, 2, true); dv.setUint16(34, 16, true);
      w(36, 'data'); dv.setUint32(40, out.length * 2, true); new Int16Array(buf, 44).set(out);
      const bytes = new Uint8Array(buf); let bin = '';
      for (let i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      return { data: 'data:audio/wav;base64,' + btoa(bin), secs: (Date.now() - this.started) / 1000 };
    },
  };
}

/* ---------- AI employee: type, speak or send a photo ---------- */
function Assistant({ me }) {
  const english = (me?.lang || (me?.role === 'Owner' || me?.role === 'Sai Markets Super Admin' ? 'en' : 'hi')) === 'en';
  const [msgs, setMsgs] = useState([]);
  const [flags, setFlags] = useState({ ai_on: true, voice_on: true });
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [rec, setRec] = useState(null);
  const [state, setState] = useState(null);
  const [err, setErr] = useState('');
  const end = useRef(null);
  const cam = useRef(null);
  const scroll = () => setTimeout(() => end.current && end.current.scrollIntoView({ block: 'end' }), 30);
  useEffect(() => { api('/ai/chat').then((d) => { setMsgs(d.messages); setFlags(d); scroll(); }).catch((e) => setErr(e.message)); }, []);
  const push = (who, t, channel = 'app') => setMsgs((m) => [...m, { who, text: t, channel, at: new Date().toISOString() }]);
  const send = async (body, shown) => {
    setErr(''); setBusy(true);
    if (shown) push('owner', shown);
    scroll();
    try {
      const r = await api('/ai/chat', { method: 'POST', body });
      if (r.heard) setMsgs((m) => { const c = [...m]; c[c.length - 1] = { ...c[c.length - 1], text: '🎙️ ' + r.heard }; return c; });
      push('bot', r.reply); setState(r.state || null);
    } catch (e) { setErr(e.message); }
    setBusy(false); scroll();
  };
  const sendText = (t) => { const v = (t ?? text).trim(); if (!v || busy) return; setText(''); send({ text: v }, v); };
  const mic = async () => {
    if (busy) return;
    if (rec) {
      const r = rec; setRec(null);
      const a = await r.stop();
      if (a.secs < 0.8) { setErr('Hold on a little longer while speaking.'); return; }
      send({ audio: a.data }, '🎙️ …');
    } else {
      try { setRec(await startRec()); setErr(''); } catch (e) { setErr('Please allow the microphone to speak to the assistant.'); }
    }
  };
  const photo = async (e) => {
    const f = e.target.files && e.target.files[0]; e.target.value = '';
    if (!f) return;
    try { const d = await photoData(f, 1280); send({ image: d, text: text.trim() }, '📷 Photo' + (text.trim() ? ': ' + text.trim() : '')); setText(''); } catch (x) { setErr(x.message); }
  };
  return html`<div class="wrap">
    <${Top} title="AI employee"/>
    <div class="pad stack" style="padding-bottom:8px;gap:10px;flex:1">
      ${!flags.ai_on ? html`<div class="err">AI is not switched on yet. Ask Sai Markets.</div>` : ''}
      ${!msgs.length ? (english ? html`<div class="card stack" style="gap:6px"><b>Just type or say it, short:</b>
        <span class="small muted">"Sharma 250kg 95 credit"</span>
        <span class="small muted">"Euro 40 rolls BOPP 20 came"</span>
        <span class="small muted">"Gupta paid 15000 UPI"</span>
        <span class="small muted">"Sharma due?" · "Today sale?" · "undo"</span>
        <span class="small muted">📷 Roll photo: which film is it</span>
        <span class="tiny muted">Nothing is saved until you press 1 · Save.</span></div>` : html`<div class="card stack" style="gap:6px"><b>Chhota sa boliye ya likhiye:</b>
        <span class="small muted">"Sharma 250kg 95 udhaar"</span>
        <span class="small muted">"Euro 40 roll BOPP 20 aaya"</span>
        <span class="small muted">"Gupta 15000 aaye UPI"</span>
        <span class="small muted">"Sharma baaki?" · "Aaj sale?" · "undo"</span>
        <span class="small muted">📷 Roll photo: kaunsa maal hai</span>
        <span class="tiny muted">"1 · Save" dabane tak kuch save nahi hota.</span></div>`) : ''}
      ${msgs.map((m) => html`<div class=${'bubble ' + (m.who === 'bot' ? 'bot' : 'me')}>${m.text}${m.channel === 'whatsapp' ? html`<span class="via">WhatsApp</span>` : ''}</div>`)}
      ${busy ? html`<div class="bubble bot muted">${english ? 'Thinking…' : 'Soch raha hoon…'}</div>` : ''}
      ${err ? html`<div class="err">${err}</div>` : ''}
      <div ref=${end}></div>
    </div>
    <div class="sticky stack" style="gap:8px">
      ${state === 'draft' ? html`<div class="grid3"><button class="btn mint sm" onClick=${() => sendText('1')}>1 · Save</button><button class="btn ghost sm" onClick=${() => sendText('2')}>2 · Change</button><button class="btn ghost sm" onClick=${() => sendText('3')}>3 · Cancel</button></div>` : ''}
      <div class="row">
        <input type="file" accept="image/*" capture="environment" ref=${cam} onChange=${photo} hidden/>
        <button class="icon" onClick=${() => cam.current.click()} aria-label="Send a photo of a roll" disabled=${busy}>${Ico.cam}</button>
        <input class="in" style="flex:1" value=${text} onInput=${(e) => setText(e.target.value)} onKeyDown=${(e) => { if (e.key === 'Enter') sendText(); }} placeholder=${rec ? 'Listening… tap ■ to send' : (english ? 'Type here…' : 'Yahan likhiye…')} aria-label="Message" disabled=${!!rec}/>
        ${text.trim() ? html`<button class="btn sm" onClick=${() => sendText()} disabled=${busy}>Send</button>`
          : html`<button class=${'icon mic' + (rec ? ' on' : '')} onClick=${mic} aria-label=${rec ? 'Stop and send' : 'Speak'} disabled=${busy || !flags.voice_on}>${rec ? '■' : Ico.mic}</button>`}
      </div>
    </div>
  </div>`;
}

/* ---------- app ---------- */
function App() {
  const route = useRoute();
  const [me, setMe] = useState(() => { try { return JSON.parse(store.get('jmk_me') || 'null'); } catch (e) { return null; } });
  const [t, setT] = useState(null);
  const [shop, setShop] = useState({});
  const toast = (msg, action) => { clearTimeout(toastTimer); setT({ msg, action }); toastTimer = setTimeout(() => setT(null), 3500); };
  useEffect(() => { api('/shop').then(setShop).catch(() => {}); }, []);
  useEffect(() => { if (token) api('/auth/me').then((d) => { setMe(d.me); store.set('jmk_me', JSON.stringify(d.me)); }).catch(() => {}); }, []);
  const out = () => { token = null; store.set('jmk_token', null); store.set('jmk_me', null); setMe(null); go('/'); };
  const parts = route.split('/').filter(Boolean);
  const staffOnly = !['', 'login'].includes(parts[0] || '');
  if (staffOnly && !token) { go('/login'); return null; }
  let page;
  switch (parts[0] || '') {
    case '': page = html`<${Stock}/>`; break;
    case 'login': page = html`<${Login} onIn=${setMe}/>`; break;
    case 'home': page = html`<${Home} me=${me} toast=${toast}/>`; break;
    case 'sale': page = html`<${Sale} toast=${toast}/>`; break;
    case 'add': page = html`<${AddStock} toast=${toast}/>`; break;
    case 'khata': page = html`<${Khata} kind=${parts[1] === 'supplier' ? 'supplier' : 'buyer'}/>`; break;
    case 'party': page = html`<${Party} id=${parts[1]} toast=${toast} shop=${shop}/>`; break;
    case 'pay': page = html`<${Pay} toast=${toast}/>`; break;
    case 'items': page = html`<${Items} toast=${toast}/>`; break;
    case 'ai': page = html`<${Assistant} me=${me}/>`; break;
    case 'more': page = html`<${More} me=${me} onOut=${out} toast=${toast}/>`; break;
    default: page = html`<div class="wrap pad"><div class="empty">Page not found. <a href="#/">Go to stock</a></div></div>`;
  }
  return html`${page}${parts[0] ? html`<${Toast} t=${t}/>` : ''}`;
}

render(html`<${App}/>`, document.getElementById('app'));
