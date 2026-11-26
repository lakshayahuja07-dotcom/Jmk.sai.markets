/* Customer AI chat box (Sai Markets). One file, no build step, shared by jmk.sai.markets and sai.markets.
   <script src="chatbox.js" data-site="jmk|sai" data-api="https://jmk.sai.markets" data-bill="#/bill"
           data-shop="JMK Traders" data-show-hash="^(#/?)?(bill)?$" defer></script>
   The AI key never reaches the page: it only calls {api}/api/public/chat. */
(function () {
  'use strict';
  var me = document.currentScript || document.querySelector('script[data-site][src*="chatbox"]');
  if (!me || window.SM_CHAT) return;
  window.SM_CHAT = true;
  var SITE = me.getAttribute('data-site') || 'sai';
  var API = (me.getAttribute('data-api') || '').replace(/\/$/, '');
  var BILL = me.getAttribute('data-bill') || '/bill/';
  var SHOP = me.getAttribute('data-shop') || 'SAI Markets';
  var SHOW = me.getAttribute('data-show-hash');
  var K = 'sm_chat_' + SITE;

  function get(k, d) { try { var v = JSON.parse(localStorage.getItem(k) || 'null'); return v == null ? d : v; } catch (e) { return d; } }
  function put(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} }
  var st = get(K, null) || { msgs: [], cart: [], note: '', wa: '' };
  if (!Array.isArray(st.msgs)) st.msgs = [];
  if (!Array.isArray(st.cart)) st.cart = [];
  function save() { st.msgs = st.msgs.slice(-30); put(K, st); }

  /* usage tracking (no personal data): bill makers call window.SM_TRACK('bill_pdf' | 'bill_wa', [item names]) */
  window.SM_TRACK = function (feature, products) {
    try {
      fetch(API + '/api/public/event', { method: 'POST', headers: { 'Content-Type': 'application/json' }, keepalive: true,
        body: JSON.stringify({ site: SITE, feature: feature, products: (products || []).slice(0, 30).map(String) }) }).catch(function () {});
    } catch (e) {}
  };

  var css = '' +
    '.smc-bar{position:sticky;top:0;z-index:9990;display:flex;justify-content:center;padding:8px 12px;background:#1B1A17;}' +
    '.smc-open{display:flex;align-items:center;gap:8px;width:100%;max-width:640px;min-height:44px;padding:0 14px;border:1px solid #4a463e;border-radius:999px;background:#2a2823;color:#f4f1ea;font:500 15px/1.2 Inter,system-ui,sans-serif;text-align:left;cursor:pointer}' +
    '.smc-open span{opacity:.8;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}' +
    '.smc-open b{flex:none;color:#ffb25b;font-weight:700}' +
    '.smc-pan{position:fixed;z-index:9991;left:50%;transform:translateX(-50%);top:62px;width:min(640px,calc(100% - 16px));max-height:calc(100vh - 76px);display:flex;flex-direction:column;background:#fff;color:#1B1A17;border-radius:16px;box-shadow:0 18px 50px rgba(0,0,0,.28);font:15px/1.4 Inter,system-ui,sans-serif;overflow:hidden}' +
    '.smc-pan[hidden]{display:none}' +
    '.smc-head{display:flex;align-items:center;justify-content:space-between;padding:10px 14px;border-bottom:1px solid #eee;font-weight:700}' +
    '.smc-x{border:0;background:none;font-size:24px;line-height:1;min-width:44px;min-height:44px;cursor:pointer;color:#555}' +
    '.smc-log{flex:1;overflow:auto;padding:12px 14px;display:flex;flex-direction:column;gap:8px;min-height:120px}' +
    '.smc-m{max-width:86%;padding:8px 12px;border-radius:14px;white-space:pre-wrap;word-wrap:break-word}' +
    '.smc-u{align-self:flex-end;background:#1B1A17;color:#fff;border-bottom-right-radius:4px}' +
    '.smc-a{align-self:flex-start;background:#f2efe8;border-bottom-left-radius:4px}' +
    '.smc-e{align-self:center;color:#b3261e;font-size:13px;text-align:center}' +
    '.smc-card{align-self:stretch;border:1px solid #e6e1d6;border-radius:12px;padding:10px 12px;display:flex;flex-direction:column;gap:6px;background:#fffdf8}' +
    '.smc-card ul{margin:0;padding-left:18px}' +
    '.smc-row{display:flex;gap:8px;flex-wrap:wrap}' +
    '.smc-btn{min-height:44px;padding:0 14px;border-radius:10px;border:1px solid #1B1A17;background:#1B1A17;color:#fff;font:600 14px Inter,system-ui,sans-serif;cursor:pointer}' +
    '.smc-btn.g{background:#fff;color:#1B1A17}' +
    '.smc-btn.wa{background:#1f9d55;border-color:#1f9d55}' +
    '.smc-cart{border-top:1px solid #eee;padding:10px 14px;display:flex;flex-direction:column;gap:6px;background:#fbfaf6}' +
    '.smc-line{display:flex;align-items:center;gap:8px}.smc-line span{flex:1}' +
    '.smc-line input{width:72px;min-height:40px;border:1px solid #ccc;border-radius:8px;padding:0 8px;font:inherit}' +
    '.smc-form{display:flex;gap:8px;padding:10px 14px;border-top:1px solid #eee}' +
    '.smc-form input{flex:1;min-width:0;min-height:44px;border:1px solid #ccc;border-radius:10px;padding:0 12px;font:inherit}' +
    '.smc-tiny{font-size:12px;color:#777}';
  var sty = document.createElement('style'); sty.textContent = css; document.head.appendChild(sty);

  function el(tag, cls, text) { var x = document.createElement(tag); if (cls) x.className = cls; if (text != null) x.textContent = text; return x; }
  var bar = el('div', 'smc-bar');
  var open = el('button', 'smc-open'); open.type = 'button'; open.setAttribute('aria-expanded', 'false');
  open.appendChild(el('b', null, '✨ Ask AI'));
  open.appendChild(el('span', null, SITE === 'jmk' ? 'Order from stock or make a bill: "BOPP 20 ke 10 roll chahiye"' : 'Make a bill or order: "bill bana do 10 box 250 ke"'));
  bar.appendChild(open);
  var pan = el('section', 'smc-pan'); pan.hidden = true; pan.setAttribute('aria-label', 'AI helper');
  var head = el('div', 'smc-head'); head.appendChild(el('span', null, 'AI helper · ' + SHOP));
  var x = el('button', 'smc-x', '×'); x.type = 'button'; x.setAttribute('aria-label', 'Close'); head.appendChild(x);
  var log = el('div', 'smc-log'); log.setAttribute('aria-live', 'polite');
  var cartBox = el('div', 'smc-cart');
  var form = el('form', 'smc-form');
  var inp = el('input'); inp.placeholder = 'Type here… Hindi or English'; inp.setAttribute('aria-label', 'Message'); inp.maxLength = 700;
  var go = el('button', 'smc-btn', 'Send'); go.type = 'submit';
  form.appendChild(inp); form.appendChild(go);
  pan.appendChild(head); pan.appendChild(log); pan.appendChild(cartBox); pan.appendChild(form);

  function mount() { if (!bar.isConnected) { document.body.insertBefore(bar, document.body.firstChild); document.body.appendChild(pan); } }
  function visible() { return !SHOW || new RegExp(SHOW).test(location.hash || ''); }
  function sync() { var v = visible(); bar.style.display = v ? '' : 'none'; if (!v) setOpen(false); }
  function setOpen(v) { pan.hidden = !v; open.setAttribute('aria-expanded', String(v)); if (v) { draw(); setTimeout(function () { inp.focus(); }, 30); } }
  open.addEventListener('click', function () { setOpen(pan.hidden); });
  x.addEventListener('click', function () { setOpen(false); });
  document.addEventListener('keydown', function (e) { if (e.key === 'Escape' && !pan.hidden) setOpen(false); });
  window.addEventListener('hashchange', sync);

  function money(v) { return 'Rs ' + (Math.round(v * 100) / 100).toLocaleString('en-IN'); }
  function billCard(b) {
    var c = el('div', 'smc-card'), tot = 0, ul = el('ul');
    b.items.forEach(function (i) { var a = i.qty * i.rate; tot += a * (1 + (i.gst || 0) / 100); ul.appendChild(el('li', null, i.name + ' × ' + i.qty + (i.rate ? ' @ ' + money(i.rate) : ' (rate?)') + (i.gst ? ' + ' + i.gst + '% GST' : ''))); });
    c.appendChild(el('b', null, (b.doc_type === 'Quotation' ? 'Quote' : 'Bill') + ' ready · ' + b.items.length + ' item' + (b.items.length > 1 ? 's' : '') + (tot ? ' · about ' + money(tot) : '')));
    c.appendChild(ul);
    var r = el('div', 'smc-row'), btn = el('button', 'smc-btn', 'Open in bill maker'); btn.type = 'button';
    btn.addEventListener('click', function () { openBill(b); });
    r.appendChild(btn); c.appendChild(r);
    c.appendChild(el('span', 'smc-tiny', 'Check it there, then download or send it.'));
    return c;
  }
  function openBill(b) {
    if (typeof window.SM_BILL_FILL === 'function') { window.SM_BILL_FILL(b); setOpen(false); return; }
    put('sm_ai_bill', b); setOpen(false); location.href = BILL;
  }
  function draw() {
    log.textContent = '';
    if (!st.msgs.length) log.appendChild(el('div', 'smc-m smc-a', SITE === 'jmk'
      ? 'Namaste ji 🙏 Tell me what you need from our stock, and I will make your order list for WhatsApp. I can also make a bill: "bill bana do: 10 roll 95 ke".'
      : 'Namaste ji 🙏 I can make a bill or quote for you ("bill: 10 box at 250, 5 kg at 90, 18% GST"), or take your order and send it to us on WhatsApp.'));
    st.msgs.forEach(function (m) {
      if (m.role === 'error') { log.appendChild(el('div', 'smc-e', m.text)); return; }
      log.appendChild(el('div', 'smc-m ' + (m.role === 'user' ? 'smc-u' : 'smc-a'), m.text));
      if (m.bill) log.appendChild(billCard(m.bill));
    });
    drawCart();
    log.scrollTop = log.scrollHeight;
  }
  function drawCart() {
    cartBox.textContent = ''; cartBox.hidden = !st.cart.length;
    if (!st.cart.length) return;
    cartBox.appendChild(el('b', null, 'Your order (' + st.cart.length + ')'));
    st.cart.forEach(function (c, i) {
      var ln = el('div', 'smc-line'); ln.appendChild(el('span', null, c.name));
      var q = el('input'); q.inputMode = 'decimal'; q.value = c.qty; q.setAttribute('aria-label', 'Quantity of ' + c.name);
      q.addEventListener('change', function () { var v = parseFloat(q.value); c.qty = v > 0 ? v : 1; save(); });
      ln.appendChild(q); ln.appendChild(el('span', 'smc-tiny', c.unit || (SITE === 'jmk' ? 'rolls' : '')));
      var rm = el('button', 'smc-x', '×'); rm.type = 'button'; rm.setAttribute('aria-label', 'Remove ' + c.name);
      rm.addEventListener('click', function () { st.cart.splice(i, 1); save(); drawCart(); });
      ln.appendChild(rm); cartBox.appendChild(ln);
    });
    var r = el('div', 'smc-row'), w = el('button', 'smc-btn wa', 'Send order on WhatsApp'), cl = el('button', 'smc-btn g', 'Clear');
    w.type = cl.type = 'button';
    w.addEventListener('click', sendWa); cl.addEventListener('click', function () { st.cart = []; st.note = ''; save(); drawCart(); });
    r.appendChild(w); r.appendChild(cl); cartBox.appendChild(r);
  }
  function sendWa() {
    if (!st.wa) { st.msgs.push({ role: 'error', text: 'WhatsApp number not set yet. Please call the shop.' }); save(); draw(); return; }
    var t = 'Hi ' + SHOP + ', I want to order:\n' + st.cart.map(function (c) { return '• ' + c.name + ' × ' + c.qty + (c.unit ? ' ' + c.unit : (SITE === 'jmk' ? ' rolls' : '')); }).join('\n') +
      (st.note ? '\nNote: ' + st.note : '') + (SITE === 'jmk' ? '\nPlease share the price.' : '');
    window.SM_TRACK('wa_order', st.cart.map(function (c) { return c.name; }));
    window.open('https://wa.me/' + st.wa + '?text=' + encodeURIComponent(t), '_blank', 'noopener');
  }

  var busy = false;
  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var text = inp.value.trim(); if (!text || busy) return;
    busy = true; go.disabled = true; inp.value = '';
    st.msgs.push({ role: 'user', text: text }); save(); draw();
    var wait = el('div', 'smc-m smc-a', '…'); log.appendChild(wait); log.scrollTop = log.scrollHeight;
    var hist = st.msgs.filter(function (m) { return m.role === 'user' || m.role === 'assistant'; }).slice(-10)
      .map(function (m) { return { role: m.role, text: String(m.text).slice(0, 790) }; });
    var h = { 'Content-Type': 'application/json' }, tok = '';
    try { tok = localStorage.getItem(me.getAttribute('data-token-key') || '_none_') || ''; } catch (e2) {}
    if (tok && tok !== 'null') h.Authorization = 'Bearer ' + tok.replace(/^"|"$/g, '');  // signed-in owner / super admin: no cap
    fetch(API + '/api/public/chat', { method: 'POST', headers: h,
      body: JSON.stringify({ site: SITE, messages: hist, cart: st.cart.slice(0, 40) }) })
      .then(function (r) { return r.json().then(function (d) { return { ok: r.ok, d: d }; }); })
      .then(function (res) {
        if (!res.ok) throw new Error((res.d && res.d.detail && typeof res.d.detail === 'string') ? res.d.detail : 'Please try again.');
        var d = res.d; if (d.wa) st.wa = d.wa;
        st.msgs.push({ role: 'assistant', text: d.reply || 'Ji.', bill: d.bill || null });
        if (d.order) { st.cart = d.order.items || []; st.note = d.order.note || ''; }
      })
      .catch(function (err) { st.msgs.push({ role: 'error', text: err && err.message && err.message !== 'Failed to fetch' ? err.message : 'No internet or the helper is down. Please try again.' }); })
      .then(function () { busy = false; go.disabled = false; save(); draw(); inp.focus(); });
  });

  function start() {  // show the chat bar only when the server has an AI key and the public chat is on
    fetch(API + '/api/public/chat').then(function (r) { return r.json(); }).then(function (d) { if (d && d.on) { mount(); sync(); } }).catch(function () {});
  }
  if (document.body) start(); else document.addEventListener('DOMContentLoaded', start);
})();
