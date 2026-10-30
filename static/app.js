/* PRESSFLOW 프론트엔드 (의존성 없음) */
'use strict';
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const ICON = {
  home: '<path d="M3 11l9-8 9 8v9a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1z"/>',
  inbox: '<path d="M22 12h-6l-2 3h-4l-2-3H2"/><path d="M5.5 5h13l3.5 7v6a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-6z"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  image: '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="8.5" cy="8.5" r="1.5"/><path d="M21 15l-5-5L5 21"/>',
  style: '<path d="M12 2l3 7h7l-5.5 4.5L18 21l-6-4-6 4 1.5-7.5L2 9h7z"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  refresh: '<path d="M21 12a9 9 0 0 1-15.5 6.2L3 16"/><path d="M3 12a9 9 0 0 1 15.5-6.2L21 8"/><path d="M21 3v5h-5M3 21v-5h5"/>',
  check: '<path d="M20 6L9 17l-5-5"/>', down: '<path d="M12 3v12m0 0l-4-4m4 4l4-4M4 21h16"/>', ext: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/>',
  copy: '<rect x="9" y="9" width="13" height="13" rx="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/>',
  doc: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M8 13h8M8 17h8"/>',
};
const ic = (n, cls = '') => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round">${ICON[n] || ''}</svg>`;

const S = { st: null, dash: null, timers: [] };
const STATUS = { drafted: 'AI 작성 완료', review: '검수 필요', approved: '발행 대기', published: '발행 완료', failed: '발행 실패', excluded: '게시 제외' };
const REGIONS_ORDER = ['강원특별자치도청', '춘천시', '원주시', '강릉시', '동해시', '태백시', '속초시', '삼척시', '홍천군', '횡성군', '영월군', '평창군', '정선군', '철원군', '화천군', '양구군', '인제군', '고성군', '양양군', '유관기관·단체', '분류 확인 필요'];

/* ───── 유틸 ───── */
async function api(path, opt = {}) {
  const o = { method: opt.method || 'GET', headers: { 'X-PF': '1' }, credentials: 'same-origin' };
  if (opt.body !== undefined) { o.headers['Content-Type'] = 'application/json'; o.body = JSON.stringify(opt.body); }
  let r;
  try { r = await fetch(path, o); } catch (e) { throw new Error('PRESSFLOW 서버에 연결할 수 없습니다. 프로그램이 켜져 있는지 확인하세요.'); }
  if (opt.raw) return r;
  let d = {}; try { d = await r.json(); } catch (e) { }
  if (r.status === 401 && S.st && S.st.user) { S.st.user = null; route(); }
  if (!r.ok) { const err = new Error(d.error || ('오류 ' + r.status)); err.data = d; err.status = r.status; throw err; }
  return d;
}
function toast(msg, kind = '') { const t = document.createElement('div'); t.className = 'toast ' + kind; t.textContent = msg; $('#toasts').append(t); setTimeout(() => t.remove(), kind === 'bad' ? 7000 : 3600); }
const fail = e => toast(e.message || String(e), 'bad');
function fmt(iso, full) { if (!iso) return '–'; const d = new Date(iso); if (isNaN(d)) return iso; const p = n => String(n).padStart(2, '0'); return (full ? d.getFullYear() + '.' : '') + `${p(d.getMonth() + 1)}.${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`; }
function ago(iso) { if (!iso) return '기록 없음'; const s = (Date.now() - new Date(iso)) / 1000; if (s < 90) return '방금 전'; if (s < 3600) return Math.round(s / 60) + '분 전'; if (s < 86400) return Math.round(s / 3600) + '시간 전'; return fmt(iso, true); }
function bytes(n) { if (n > 1e9) return (n / 1e9).toFixed(1) + ' GB'; if (n > 1e6) return (n / 1e6).toFixed(1) + ' MB'; if (n > 1e3) return Math.round(n / 1e3) + ' KB'; return n + ' B'; }
function regBadge(r) { const c = r === '강원특별자치도청' ? 'prov' : r === '유관기관·단체' ? 'org' : r === '분류 확인 필요' ? 'unk' : ''; return `<span class="badge reg ${c}">${esc(r || '미분류')}</span>`; }
const stBadge = s => `<span class="badge ${s}">${STATUS[s] || s}</span>`;
function modal(html, cls = '') { const m = $('#modal'); m.innerHTML = `<div class="modal ${cls}">${html}</div>`; m.hidden = false; m.onclick = e => { if (e.target === m) closeModal(); }; return m; }
function closeModal() { const m = $('#modal'); m.hidden = true; m.innerHTML = ''; }
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeModal(); });
function confirmBox(title, body, okLabel = '확인', danger = false) {
  return new Promise(res => {
    modal(`<h2 style="font-size:18px;margin-bottom:10px">${esc(title)}</h2><div class="muted" style="margin-bottom:18px">${body}</div><div class="row" style="justify-content:flex-end"><button class="btn" id="cb-no">취소</button><button class="btn ${danger ? 'danger' : 'pri'}" id="cb-ok">${esc(okLabel)}</button></div>`, 'sm');
    $('#cb-no').onclick = () => { closeModal(); res(false); }; $('#cb-ok').onclick = () => { closeModal(); res(true); };
  });
}
function promptBox(title, label, ph = '') {
  return new Promise(res => {
    modal(`<h2 style="font-size:18px;margin-bottom:12px">${esc(title)}</h2><label class="f">${esc(label)}<input type="text" id="pb-v" placeholder="${esc(ph)}"></label><div class="row mt" style="justify-content:flex-end"><button class="btn" id="pb-no">취소</button><button class="btn pri" id="pb-ok">확인</button></div>`, 'sm');
    $('#pb-v').focus(); $('#pb-no').onclick = () => { closeModal(); res(null); }; const ok = () => { const v = $('#pb-v').value.trim(); closeModal(); res(v); };
    $('#pb-ok').onclick = ok; $('#pb-v').onkeydown = e => { if (e.key === 'Enter') ok(); };
  });
}
async function copyText(text, html) {
  try {
    if (html && window.ClipboardItem) await navigator.clipboard.write([new ClipboardItem({ 'text/html': new Blob([html], { type: 'text/html' }), 'text/plain': new Blob([text], { type: 'text/plain' }) })]);
    else await navigator.clipboard.writeText(text);
    toast('복사했습니다.', 'ok');
  } catch (e) { const ta = document.createElement('textarea'); ta.value = text; document.body.append(ta); ta.select(); document.execCommand('copy'); ta.remove(); toast('복사했습니다.', 'ok'); }
}
async function downloadPost(path, body, name) {
  const r = await api(path, { method: 'POST', body, raw: true });
  if (!r.ok) { let d = {}; try { d = await r.json(); } catch (e) { } throw new Error(d.error || '다운로드 실패'); }
  const b = await r.blob(); const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(a.href), 4000);
}
function clearTimers() { S.timers.forEach(clearInterval); S.timers = []; }

/* ───── 라우터 ───── */
function parseHash() { const h = location.hash.replace(/^#\/?/, ''); const [p, q] = h.split('?'); return { path: p || 'dashboard', q: Object.fromEntries(new URLSearchParams(q || '')) }; }
function go(h) { location.hash = h; }
async function boot() {
  try { S.st = await api('/api/state'); } catch (e) { $('#root').innerHTML = `<div class="auth-form" style="min-height:100vh"><div class="card">${esc(e.message)}</div></div>`; return; }
  route();
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => { });
}
window.addEventListener('hashchange', () => { if (S.st && S.st.user) route(); });
async function route() {
  clearTimers();
  const st = S.st;
  if (!st.has_admin) return wizard(0);
  if (!st.user) return loginView();
  if (!st.setup_done && st.user.role === 'admin') return wizard(1);
  const { path, q } = parseHash();
  const [name, arg] = path.split('/');
  const pages = { dashboard: pDashboard, inbox: pInbox, blog: pBlog, article: pArticle, photos: pPhotos, style: pStyle, backup: pBackup, settings: pSettings, audit: pAudit };
  shell(name);
  const el = $('#page');
  el.innerHTML = '<div class="empty muted">불러오는 중…</div>';
  try { await (pages[name] || pDashboard)(el, q, arg); } catch (e) { el.innerHTML = `<div class="notice bad">${esc(e.message)}</div>`; }
}
const NAV = [['dashboard', '대시보드', 'home'], ['inbox', '보도자료 자료함', 'inbox'], ['blog', '블로그 기사 관리', 'edit'], ['photos', '사진저장함', 'image'], ['style', '블로그 스타일', 'style'], ['backup', '백업·보존', 'shield'], ['settings', '설정', 'gear'], ['audit', '활동 기록', 'list']];
const TITLES = { dashboard: ['대시보드', '수집부터 발행까지 한눈에'], inbox: ['보도자료 자료함', '지역·기관별로 자동 분류된 원문'], blog: ['블로그 기사 관리', 'AI 교정 → 검수 → 발행 대기 → 발행 완료'], article: ['기사 상세', ''], photos: ['사진저장함', '기사 제목으로 저장된 원본 사진'], style: ['블로그 스타일 가이드', '기존 공식 블로그의 형식을 새 기사에 적용'], backup: ['백업·보존', '암호화 백업과 복구 테스트'], settings: ['설정', '메일·블로그·AI·사용자'], audit: ['활동 기록', '누가 언제 무엇을 했는지'] };
function shell(active) {
  const u = S.st.user;
  if (!$('#page')) {
    $('#root').innerHTML = `<div class="shell"><aside class="side"><div class="brand"><img src="/static/logo.svg" alt=""><div><b>PRESSFLOW</b><span>강원사회복지신문</span></div></div>
    <nav class="nav" id="nav"></nav><div class="side-foot"><div class="u"><div class="avatar">${esc((u.display || u.username)[0])}</div><div class="grow"><b>${esc(u.display)}</b><div class="faint">${u.role === 'admin' ? '최고관리자' : '편집자'}</div></div></div><button data-act="logout">로그아웃</button></div></aside>
    <main class="main"><header class="top"><div class="grow"><h1 id="ttl"></h1><div class="sub" id="sub"></div></div><div id="top-act" class="row"></div></header><div class="page" id="page"></div></main></div>`;
  }
  const items = NAV.filter(n => n[0] !== 'audit' || u.role === 'admin');
  const d = S.dash;
  $('#nav').innerHTML = `<div class="lbl">업무</div>` + items.slice(0, 4).map(n => navItem(n, active, d)).join('') + `<div class="lbl">관리</div>` + items.slice(4).map(n => navItem(n, active, d)).join('');
  const t = TITLES[active] || TITLES.dashboard; $('#ttl').textContent = t[0]; $('#sub').textContent = t[1];
  $('#top-act').innerHTML = active === 'dashboard' || active === 'inbox' ? `<button class="btn pri" data-act="collect">${ic('refresh')} 지금 메일 수집</button>` : '';
}
function navItem(n, active, d) {
  let cnt = '';
  if (d && n[0] === 'blog' && d.blog.review + d.blog.pending) cnt = `<span class="cnt warn">${d.blog.review}</span>`;
  return `<a href="#/${n[0]}" class="${active === n[0] || (active === 'article' && n[0] === 'blog') ? 'on' : ''}">${ic(n[2])}<span>${n[1]}</span>${cnt}</a>`;
}

/* ───── 이벤트 위임 ───── */
const ACT = {};
document.addEventListener('click', e => {
  const el = e.target.closest('[data-act]'); if (!el) return;
  const fn = ACT[el.dataset.act]; if (fn) { e.preventDefault(); Promise.resolve(fn(el, e)).catch(fail); }
});
ACT.logout = async () => { await api('/api/logout', { method: 'POST', body: {} }); S.st.user = null; S.dash = null; route(); };
ACT.collect = async el => {
  el.disabled = true;
  try { const r = await api('/api/collect/run', { method: 'POST', body: {} }); toast(r.running ? '이미 수집 중입니다.' : '메일 수집을 시작했습니다.', 'ok'); pollCollect(); } finally { el.disabled = false; }
};
function pollCollect() {
  let n = 0; const iv = setInterval(async () => {
    n++; let s; try { s = await api('/api/collect/status'); } catch (e) { clearInterval(iv); return; }
    const b = $('[data-act=collect]'); if (b) b.innerHTML = s.running ? `${ic('refresh')} 수집 중 ${esc(s.progress || '')}` : `${ic('refresh')} 지금 메일 수집`;
    if (!s.running || n > 240) { clearInterval(iv); if (s.last && !s.last.ok && s.last.error) toast(s.last.error, 'bad'); else toast('수집이 끝났습니다.', 'ok'); const r = parseHash().path.split('/')[0]; if (['dashboard', 'inbox', 'blog'].includes(r)) route(); }
  }, 2500); S.timers.push(iv);
}

/* ───── 로그인 ───── */
function authFrame(inner) {
  return `<div class="auth"><section class="auth-art"><div class="brand"><img src="/static/logo.svg" alt=""><div><b>PRESSFLOW</b><span style="color:#9fc3bf">강원사회복지신문 통합 콘텐츠 자동화 플랫폼</span></div></div>
  <div><h2>보도자료에서 블로그까지,<br><em>하나의 흐름</em>으로.</h2><p class="mt">메일 수집 · 사진 정리 · 맞춤법 교정 · 블로그 초안 · 발행 기록을 한곳에서. 사실관계는 원문 그대로, 확인이 필요한 부분은 사람에게 먼저 묻습니다.</p></div>
  <div class="flowline"><span>메일 수집</span><i>→</i><span>분류·저장</span><i>→</i><span>AI 교정</span><i>→</i><span>검수·승인</span><i>→</i><span>블로그 게시</span></div></section>
  <section class="auth-form"><div class="auth-card">${inner}</div></section></div>`;
}
function loginView() {
  $('#root').innerHTML = authFrame(`<h1>로그인</h1><p class="muted mb">이 컴퓨터에 설치된 PRESSFLOW에 로그인합니다.</p>
  <form id="lf" class="col"><label class="f">아이디<input type="text" id="lu" autocomplete="username" autofocus></label><label class="f">비밀번호<input type="password" id="lp" autocomplete="current-password"></label>
  <button class="btn pri" style="padding:11px">로그인</button><div id="le" class="notice bad hide"></div></form>`);
  $('#lf').onsubmit = async e => {
    e.preventDefault();
    try { await api('/api/login', { method: 'POST', body: { username: $('#lu').value, password: $('#lp').value } }); S.st = await api('/api/state'); route(); }
    catch (er) { const b = $('#le'); b.textContent = er.message; b.classList.remove('hide'); }
  };
}

/* ───── 첫 실행 마법사 ───── */
const W = { step: 0 };
function wizard(step) {
  W.step = step;
  const bar = `<div class="wiz-steps">${[0, 1, 2, 3, 4].map(i => `<i class="${i < step ? 'on' : i === step ? 'cur' : ''}"></i>`).join('')}</div>`;
  const root = $('#root');
  const put = html => { root.innerHTML = authFrame(bar + html); };
  const S0 = () => {
    put(`<h1>PRESSFLOW 시작하기</h1><p class="muted mb">먼저 이 프로그램을 관리할 최고관리자 계정을 만듭니다. (이 컴퓨터에만 저장됩니다)</p>
    <form id="f" class="col"><label class="f">표시 이름<input type="text" id="d" placeholder="예: 편집국장" value=""></label>
    <label class="f">아이디<small>영문·숫자 3자 이상</small><input type="text" id="u" autocomplete="username"></label>
    <label class="f">비밀번호<small>8자 이상</small><input type="password" id="p" autocomplete="new-password"></label>
    <button class="btn pri" style="padding:11px">계정 만들고 계속</button><div id="e" class="notice bad hide"></div></form>`);
    $('#f').onsubmit = async e => { e.preventDefault(); try { await api('/api/setup/admin', { method: 'POST', body: { username: $('#u').value, password: $('#p').value, display: $('#d').value } }); S.st = await api('/api/state'); wizard(1); } catch (er) { $('#e').textContent = er.message; $('#e').classList.remove('hide'); } };
  };
  const S1 = () => {
    put(`<h1>네이버 메일 연결</h1><p class="muted mb">보도자료를 받는 신문사 네이버 메일을 연결합니다. 메일은 <b>읽기 전용</b>으로만 열며, 삭제·이동·읽음 표시를 바꾸지 않습니다.</p>
    <form id="f" class="col"><label class="f">네이버 아이디<input type="text" id="u" placeholder="예: gwwelfare" value="${esc(S.st.mail_user || '')}"></label>
    <label class="f">비밀번호 또는 애플리케이션 비밀번호<small>2단계 인증을 쓰면 ‘애플리케이션 비밀번호’를 발급해 입력하세요. 암호화되어 이 컴퓨터에만 저장됩니다.</small><input type="password" id="p" autocomplete="off"></label>
    <div class="notice info">네이버 메일 → 환경설정 → <b>POP3/IMAP 설정</b>에서 IMAP 사용을 ‘사용함’으로 먼저 바꿔 주세요.</div>
    <div class="grid g2"><label class="f">자동 수집 주기(분)<input type="number" id="m" value="15" min="5"></label><label class="f">최초 수집 범위(일)<input type="number" id="i" value="7" min="1" max="60"></label></div>
    <div class="row"><button type="button" class="btn" id="t">연결 테스트</button><span id="tr" class="small"></span></div>
    <div class="row between"><button type="button" class="btn ghost" id="sk">나중에 하기</button><button class="btn pri" style="padding:11px 22px">저장하고 계속</button></div></form>`);
    $('#t').onclick = async () => { $('#tr').textContent = '확인 중…'; const r = await api('/api/mail/test', { method: 'POST', body: { user: $('#u').value, password: $('#p').value } }); $('#tr').innerHTML = r.ok ? `<span style="color:var(--green)">✔ 연결 성공 (받은편지함 ${r.total}통)</span>` : `<span style="color:var(--red)">${esc(r.error)}</span>`; };
    $('#sk').onclick = () => wizard(2);
    $('#f').onsubmit = async e => { e.preventDefault(); try { await api('/api/settings/mail', { method: 'POST', body: { user: $('#u').value, password: $('#p').value, minutes: +$('#m').value, initial_days: +$('#i').value } }); wizard(2); } catch (er) { fail(er); } };
  };
  const S2 = () => {
    put(`<h1>공식 블로그 연결</h1><p class="muted mb">새 블로그를 만들지 않고 <b>현재 운영 중인 강원사회복지신문 네이버 블로그</b>를 등록합니다. 기존 게시물로 기사 형식을 분석하는 데 쓰입니다.</p>
    <form id="f" class="col"><label class="f">블로그 주소<small>예: https://blog.naver.com/블로그아이디</small><input type="text" id="b" placeholder="https://blog.naver.com/…" value="${esc(S.st.blog_url || '')}"></label>
    <div class="notice warn"><span>네이버는 공식 블로그 글쓰기 API를 종료했습니다. 그래서 PRESSFLOW는 로그인 정보를 받지 않고, <b>완성된 기사·사진을 편집기에 쉽게 옮기는 ‘게시 도우미’</b> 방식으로 동작합니다. 게시 후 주소를 기록하면 중복 발행이 차단됩니다.</span></div>
    <div class="row between"><button type="button" class="btn ghost" id="sk">나중에 하기</button><button class="btn pri" style="padding:11px 22px">저장하고 계속</button></div></form>`);
    $('#sk').onclick = () => wizard(3);
    $('#f').onsubmit = async e => { e.preventDefault(); try { await api('/api/settings/blog', { method: 'POST', body: { url: $('#b').value } }); wizard(3); } catch (er) { fail(er); } };
  };
  const S3 = async () => {
    const s = await api('/api/settings');
    put(`<h1>교정 방식과 백업 위치</h1><p class="muted mb">기본은 이 컴퓨터 안에서 동작하는 규칙 기반 교정입니다. 원하면 Claude(AI)를 켜서 더 정밀하게 교정할 수 있습니다.</p>
    <form id="f" class="col"><label class="check"><input type="checkbox" id="ae"><span>AI(Claude) 교정 사용 <small class="muted" style="display:block;font-weight:400">켜면 기사 본문이 Anthropic API로 전송됩니다. 결과는 원문과 대조 검증을 통과해야만 채택됩니다.</small></span></label>
    <label class="f hide" id="akw">Anthropic API 키<input type="password" id="ak" placeholder="sk-ant-…" autocomplete="off"></label>
    <label class="f">백업 저장 폴더<small>가능하면 <b>다른 드라이브·외장하드·NAS·클라우드 동기화 폴더</b>를 지정하세요. 같은 디스크에만 있으면 디스크 고장 때 함께 사라집니다.</small><input type="text" id="bd" value="${esc(s.backup.dir)}"></label>
    <div class="row between"><button type="button" class="btn ghost" id="sk">건너뛰기</button><button class="btn pri" style="padding:11px 22px">저장하고 계속</button></div></form>`);
    $('#ae').onchange = e => $('#akw').classList.toggle('hide', !e.target.checked);
    $('#sk').onclick = () => wizard(4);
    $('#f').onsubmit = async e => { e.preventDefault(); try { await api('/api/settings/ai', { method: 'POST', body: { enabled: $('#ae').checked, key: $('#ak').value } }); const r = await api('/api/settings/backup', { method: 'POST', body: { dir: $('#bd').value, auto: true } }); if (r.same_drive) toast('백업 폴더가 데이터와 같은 드라이브입니다. 나중에 다른 드라이브로 바꾸는 것을 권장합니다.'); wizard(4); } catch (er) { fail(er); } };
  };
  const S4 = async () => {
    const k = await api('/api/recovery-key');
    put(`<h1>복구 키를 보관하세요</h1><p class="muted mb">모든 백업과 비밀번호는 아래 <b>복구 키</b>로 암호화됩니다. 이 컴퓨터가 고장 나면 이 키가 있어야 백업을 열 수 있습니다. 지금 복사해 <b>USB·종이·비밀번호 관리자</b>에 따로 보관하세요.</p>
    <div class="keybox" id="kb">${esc(k.key)}</div><div class="row mt"><button class="btn" id="cp">${ic('copy')} 복사</button></div>
    <label class="check mt"><input type="checkbox" id="ok"><span>복구 키를 안전한 곳에 따로 보관했습니다.</span></label>
    <button class="btn pri mt" id="fin" style="padding:11px" disabled>설정 마치고 시작하기</button>`);
    $('#cp').onclick = () => copyText(k.key); $('#ok').onchange = e => $('#fin').disabled = !e.target.checked;
    $('#fin').onclick = async () => { await api('/api/setup/finish', { method: 'POST', body: {} }); S.st = await api('/api/state'); go('#/dashboard'); route(); toast('설정 완료! 메일 수집을 시작합니다.', 'ok'); };
  };
  [S0, S1, S2, S3, S4][step]();
}

/* ───── 대시보드 ───── */
async function pDashboard(el) {
  const render = async () => {
    const d = await api('/api/dashboard'); S.dash = d; shell('dashboard');
    const c = d.collect, a = d.ai, b = d.blog, s = d.system;
    const ok = (v, t) => `<span class="dot ${v ? 'ok' : 'bad'}"></span>${t}`;
    el.innerHTML = `
    ${S.st.update && S.st.update.available && S.st.user.role === 'admin' ? `<div class="notice ok mb"><span><b>새 버전 ${esc(S.st.update.latest)} 이(가) 있습니다.</b> 자동 설치가 켜져 있으면 잠시 쉬는 시간에 설치됩니다. <a href="#/settings?tab=update">자세히 →</a></span></div>` : ''}
    ${!s.mail.configured ? `<div class="notice warn mb">${ic('inbox')}<span><b>네이버 메일이 아직 연결되지 않았습니다.</b> 설정에서 메일을 연결하면 15분마다 자동으로 수집합니다. <a href="#/settings?tab=mail">연결하기 →</a></span></div>` : ''}
    ${s.guide !== 'confirmed' ? `<div class="notice info mb"><span><b>블로그 스타일 가이드가 아직 확정되지 않았습니다.</b> 확정 전에는 ‘기본형’으로 초안을 만들고 확인 표시를 남깁니다. <a href="#/style">스타일 분석하기 →</a></span></div>` : ''}
    <div class="group-h">자료 수집</div>
    <div class="kpi"><div class="card"><div class="stat"><span class="v mono">${c.mails_today}</span><span class="k">오늘 들어온 메일</span></div></div>
      <div class="card a"><div class="stat"><span class="v mono">${c.articles_today}</span><span class="k">오늘 수집된 보도자료</span></div></div>
      <div class="card b"><div class="stat"><span class="v mono">${c.photos}</span><span class="k">저장된 사진</span></div></div>
      <div class="card c"><div class="stat"><span class="v mono">${c.txt}</span><span class="k">생성된 메모(TXT) 파일</span></div></div></div>
    <div class="group-h">AI 기사 처리</div>
    <div class="kpi" style="grid-template-columns:repeat(3,1fr)"><div class="card"><div class="stat"><span class="v mono">${a.corrected}</span><span class="k">AI 교정 완료</span></div></div>
      <div class="card a"><div class="stat"><span class="v mono">${a.need_review}</span><span class="k">교정·사실관계 검수 필요</span></div></div>
      <div class="card b"><div class="stat"><span class="v mono">${a.drafts}</span><span class="k">블로그 초안 생성 완료</span></div></div></div>
    <div class="group-h">블로그 발행</div>
    <div class="kpi"><a class="card" href="#/blog?tab=approved" style="text-decoration:none;color:inherit"><div class="stat"><span class="v mono">${b.pending}</span><span class="k">발행 대기</span></div></a>
      <a class="card c" href="#/blog?tab=published" style="text-decoration:none;color:inherit"><div class="stat"><span class="v mono">${b.published}</span><span class="k">발행 완료</span></div></a>
      <a class="card d" href="#/blog?tab=failed" style="text-decoration:none;color:inherit"><div class="stat"><span class="v mono">${b.failed}</span><span class="k">발행 실패</span></div></a>
      <a class="card" href="#/blog?tab=excluded" style="text-decoration:none;color:inherit"><div class="stat"><span class="v mono">${b.excluded}</span><span class="k">게시 제외</span></div></a></div>
    <div class="grid g-main mt-l">
      <div class="col">
        <div class="card"><h2>지역별 수집 건수 <span class="faint small" style="font-weight:400">전체 · 오늘 신규 표시</span></h2>
          <div class="regions">${REGIONS_ORDER.map(r => { const n = c.regions[r] || 0, t = c.regions_today[r] || 0; return `<div class="regchip ${n ? '' : 'zero'}" data-act="goRegion" data-r="${esc(r)}"><span class="nm">${esc(r.replace('강원특별자치도청', '강원도청'))}</span>${t ? `<span class="tdy">+${t}</span>` : ''}<span class="ct mono">${n}</span></div>`; }).join('')}</div></div>
        <div class="card"><h2>최근 수집한 기사</h2>${d.recent.length ? `<table class="t"><tbody>${d.recent.map(r => `<tr class="click" onclick="go('#/article/${r.id}')"><td class="title"><span class="tt">${esc(r.title)}</span></td><td>${regBadge(r.region)}</td><td>${stBadge(r.status)}</td><td class="muted small">${fmt(r.at)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">아직 수집된 기사가 없습니다.</div>'}</div>
      </div>
      <div class="card"><h2>시스템 상태</h2><ul class="sys">
        <li><span class="k">네이버 메일</span><span class="v">${s.mail.configured ? ok(s.mail.last_ok !== false, s.mail.last_ok === false ? '수집 오류' : '연결됨') : ok(false, '미연결')}</span></li>
        <li><span class="k">블로그 연동</span><span class="v">${s.blog.configured ? `<span class="dot warn"></span>${esc(s.blog.mode)}` : ok(false, '미등록')}</span></li>
        <li><span class="k">마지막 메일 수집</span><span class="v">${ago(s.last_collect)}${s.running ? ' <span class="badge">수집 중</span>' : ''}</span></li>
        <li><span class="k">마지막 게시 처리</span><span class="v">${ago(s.last_publish)}</span></li>
        <li><span class="k">마지막 백업 성공</span><span class="v">${ago(s.last_backup)}</span></li>
        <li><span class="k">복구 테스트</span><span class="v">${s.restore_test ? ok(s.restore_test.ok, ago(s.restore_test.at)) : '<span class="muted">아직 없음</span>'}</span></li>
        <li><span class="k">AI 교정</span><span class="v">${s.ai ? ok(true, 'AI + 규칙') : '규칙 기반'}</span></li>
        <li><span class="k">자동화 오류</span><span class="v">${s.errors.length ? `<span style="color:var(--red)">${s.errors.length}건</span>` : ok(true, '없음')}</span></li></ul>
        ${s.errors.length ? `<div class="notice bad mt">${s.errors.map(e => esc(e.msg)).join('<br>')}</div>` : ''}
        ${s.last_collect ? '' : ''}</div></div>`;
  };
  await render();
  S.timers.push(setInterval(() => { if (parseHash().path.startsWith('dashboard') && !document.hidden) render().catch(() => { }); }, 20000));
}
ACT.goRegion = el => go('#/inbox?region=' + encodeURIComponent(el.dataset.r));

/* ───── 기사 목록 공통 ───── */
function artTable(items, opts = {}) {
  if (!items.length) return `<div class="empty">${ic('doc')}<div>해당하는 기사가 없습니다.</div></div>`;
  return `<div class="tblwrap"><table class="t"><thead><tr><th>제목</th><th>지역</th><th>기관</th><th>수신</th><th>사진</th><th>교정</th><th>상태</th></tr></thead><tbody>${items.map(a => `<tr class="click" onclick="go('#/article/${a.id}')">
    <td class="title"><span class="tt">${esc(a.title)}</span>${a.open_blocks ? `<span class="badge failed" style="margin-top:3px">확인 필요 ${a.open_blocks}</span>` : ''}</td><td>${regBadge(a.region)}</td><td class="muted small org" title="${esc(a.org || '')}">${esc(a.org || '')}</td><td class="muted small mono">${fmt(a.received_at)}</td><td class="mono">${a.photos}</td>
    <td class="small">${esc(a.proof)}</td><td>${stBadge(a.status)}</td></tr>`).join('')}</tbody></table></div>`;
}
function pager(total, page, per, act) {
  const pages = Math.ceil(total / per); if (pages <= 1) return '';
  return `<div class="pager"><button class="btn sm" ${page <= 1 ? 'disabled' : ''} data-act="${act}" data-p="${page - 1}">이전</button><span class="muted small">${page} / ${pages} · 총 ${total}건</span><button class="btn sm" ${page >= pages ? 'disabled' : ''} data-act="${act}" data-p="${page + 1}">다음</button></div>`;
}

/* ───── 자료함 ───── */
const IB = { region: '전체', q: '', from: '', to: '', page: 1 };
async function pInbox(el, q) {
  if (q.region) { IB.region = q.region; IB.page = 1; }
  const regs = await api('/api/regions');
  const params = new URLSearchParams({ region: IB.region, q: IB.q, from: IB.from, to: IB.to, page: IB.page });
  const list = await api('/api/articles?' + params);
  el.innerHTML = `<div class="split"><div class="card flat rlist"><button class="${IB.region === '전체' ? 'on' : ''}" data-act="ibRegion" data-r="전체">전체 자료함<span class="n mono">${regs.total}</span></button>
    <div class="sec">강원특별자치도</div>${regs.regions.slice(0, 1).map(rb).join('')}<div class="sec">7개 시</div>${regs.regions.slice(1, 8).map(rb).join('')}<div class="sec">11개 군</div>${regs.regions.slice(8, 19).map(rb).join('')}<div class="sec">기타</div>${regs.regions.slice(19).map(rb).join('')}</div>
    <div><div class="filters"><input type="search" id="ibq" placeholder="제목·기관·본문 검색" value="${esc(IB.q)}"><input type="date" id="ibf" value="${IB.from}" style="width:150px"><span class="muted">~</span><input type="date" id="ibt" value="${IB.to}" style="width:150px"><button class="btn" data-act="ibSearch">검색</button>
    <span class="right muted small">${esc(IB.region)} · ${list.total}건</span></div><div class="card" style="padding:6px 10px">${artTable(list.items)}</div>${pager(list.total, list.page, list.per, 'ibPage')}</div></div>`;
  $('#ibq').onkeydown = e => { if (e.key === 'Enter') ACT.ibSearch(); };
  function rb(r) { return `<button class="${IB.region === r.name ? 'on' : ''}" data-act="ibRegion" data-r="${esc(r.name)}">${esc(r.name.replace('강원특별자치도청', '강원도청'))}<span class="n mono">${r.count}</span></button>`; }
}
ACT.ibRegion = el => { IB.region = el.dataset.r; IB.page = 1; history.replaceState(null, '', '#/inbox'); route(); };
ACT.ibSearch = () => { IB.q = $('#ibq').value; IB.from = $('#ibf').value; IB.to = $('#ibt').value; IB.page = 1; route(); };
ACT.ibPage = el => { IB.page = +el.dataset.p; route(); };

/* ───── 블로그 기사 관리 ───── */
const BL = { tab: 'drafted', page: 1 };
async function pBlog(el, q) {
  if (q.tab) BL.tab = q.tab;
  const d = S.dash || await api('/api/dashboard'); S.dash = d;
  const cnt = { drafted: d.blog.drafted, review: d.blog.review, approved: d.blog.pending, published: d.blog.published, failed: d.blog.failed, excluded: d.blog.excluded };
  const list = await api(`/api/articles?status=${BL.tab}&page=${BL.page}`);
  const hints = { drafted: '교정과 블로그 형식 적용이 끝난 기사입니다. 내용을 확인하고 발행 승인을 누르세요.', review: '사실관계·오탈자·사진 권한 등 사람이 확인해야 하는 기사입니다. 항목을 해결해야 발행 승인이 가능합니다.', approved: '게시 준비가 끝난 기사입니다. 기사 상세의 ‘게시 도우미’로 네이버 블로그에 올린 뒤 주소를 기록하세요.', published: '공식 네이버 블로그에 게시된 기사입니다. 같은 기사는 다시 게시되지 않습니다.', failed: '게시 과정에서 오류가 기록된 기사입니다. 사유를 확인하고 다시 승인하세요.', excluded: '관리자가 게시하지 않기로 한 기사입니다.' };
  el.innerHTML = `<div class="tabs">${Object.keys(STATUS).map(k => `<button class="${BL.tab === k ? 'on' : ''}" data-act="blTab" data-t="${k}">${STATUS[k]}<span class="n mono">${cnt[k] || 0}</span></button>`).join('')}</div>
   <div class="muted small mb">${hints[BL.tab]}</div><div class="card" style="padding:6px 10px">${artTable(list.items)}</div>${pager(list.total, list.page, list.per, 'blPage')}`;
}
ACT.blTab = el => { BL.tab = el.dataset.t; BL.page = 1; route(); };
ACT.blPage = el => { BL.page = +el.dataset.p; route(); };

/* ───── 기사 상세 ───── */
const AT = { tab: 'compare' };
let CUR = null, KIT = null;
async function pArticle(el, q, id) {
  const [a, kit] = await Promise.all([api('/api/articles/' + id), api(`/api/articles/${id}/publish-kit`)]);
  CUR = a; KIT = kit;
  const diffA = await api(`/api/articles/${id}/diff?a=original&b=${a.edited ? 'final' : 'corrected'}`);
  CUR._diff = diffA.html;
  $('#ttl').textContent = '기사 상세'; $('#sub').textContent = `#${a.id} · ${a.mail.sender_name || a.mail.sender_email}`;
  const open = a.flags.filter(f => !f.resolved && (f.sev === 'block' || f.sev === 'warn'));
  const blocks = a.flags.filter(f => f.sev === 'block' && !f.resolved).length;
  el.innerHTML = `<div class="row mb"><a href="#/${a.status === 'published' || a.status === 'approved' ? 'blog' : 'inbox'}" class="muted small">← 목록으로</a></div>
  <div class="card art-head"><div class="row wrap gap-s mb">${stBadge(a.status)}${regBadge(a.region)}<span class="badge">${esc(a.stage)}</span><span class="badge">v${a.version}</span>${a.edited ? '<span class="badge review">수정본</span>' : ''}<span class="muted small right">수신 ${fmt(a.received_at, true)}</span></div>
    <h1>${esc(a.title)}</h1><div class="muted small mt">${esc(a.org || '')} · ${esc(a.mail.sender_email)} · 분류 근거: ${esc(a.region_reason || '–')}</div>
    ${a.blog_url ? `<div class="notice ok mt">${ic('check')}<span><b>발행 완료</b> · ${fmt(a.published_at, true)} · ${esc(a.published_by || '')} · v${a.published_version} · <a href="${esc(a.blog_url)}" target="_blank" rel="noopener">${esc(a.blog_url)}</a></span></div>` : ''}
    ${a.status === 'excluded' ? `<div class="notice info mt"><span>게시 제외됨${a.exclude_reason ? ': ' + esc(a.exclude_reason) : ''}</span></div>` : ''}${a.status === 'failed' ? `<div class="notice bad mt"><span><b>발행 실패</b>: ${esc(a.fail_reason || '')}</span></div>` : ''}
    <div class="row wrap mt">${actionButtons(a, blocks)}</div></div>
  ${open.length ? `<div class="card mt flat"><h2>${blocks ? '⚠ 발행 전 확인이 필요합니다' : '참고할 항목'} <span class="badge ${blocks ? 'failed' : 'review'}">${open.length}</span></h2><div class="flags">${open.slice(0, 4).map(f => flagHtml(f)).join('')}</div>${open.length > 4 ? `<div class="small muted mt"><a href="#" data-act="atTab" data-t="flags">전체 ${open.length}건 보기</a></div>` : ''}</div>` : ''}
  <div class="tabs mt-l">${[['compare', '비교 보기'], ['edit', '편집'], ['flags', `확인 항목 <span class="n">${a.flags.filter(f => f.sev !== 'info').length + a.suggestions.length}</span>`], ['photos', `사진 <span class="n">${a.photo_list.length}</span>`], ['publish', '게시 도우미'], ['source', '원본·파일']].map(t => `<button class="${AT.tab === t[0] ? 'on' : ''}" data-act="atTab" data-t="${t[0]}">${t[1]}</button>`).join('')}</div><div id="at-body"></div>`;
  renderTab();
}
function actionButtons(a, blocks) {
  const b = [];
  if (['drafted', 'review', 'failed'].includes(a.status)) b.push(`<button class="btn pri" data-act="approve">${ic('check')} 발행 승인</button>`);
  if (a.status === 'approved') b.push(`<button class="btn" data-act="unapprove">승인 취소</button>`);
  if (a.status !== 'published' && a.status !== 'excluded') b.push(`<button class="btn" data-act="reproof">${ic('refresh')} 다시 교정</button><button class="btn danger" data-act="exclude">게시 제외</button>`);
  if (a.status === 'excluded') b.push(`<button class="btn" data-act="restore">제외 해제</button>`);
  b.push(`<span class="right"></span><a class="btn" href="/files/txt/${a.id}/orig">${ic('down')} 원문 TXT</a>`);
  if (a.txt_corr) b.push(`<a class="btn" href="/files/txt/${a.id}/corr">${ic('down')} 교정본 TXT</a>`);
  return b.join('');
}
const flagHtml = (f, withBtn) => `<div class="flag ${f.resolved ? 'done' : f.sev}"><span class="m">${f.resolved ? '✔ ' : ''}${esc(f.msg)}${f.resolved ? `<span class="small"> — ${esc(f.by || '')} 확인${f.note ? ': ' + esc(f.note) : ''}</span>` : ''}</span>${withBtn && !f.resolved && f.sev !== 'info' ? `<button class="btn sm" data-act="resolve" data-c="${esc(f.code)}">확인함</button>` : ''}</div>`;
ACT.atTab = el => { AT.tab = el.dataset.t; $$('.tabs button').forEach(b => b.classList.toggle('on', b.dataset.t === AT.tab)); renderTab(); };
function renderTab() {
  const a = CUR, el = $('#at-body'); if (!el) return;
  if (AT.tab === 'compare') {
    el.innerHTML = `<div class="cmp"><div class="pane"><h3>수집한 원문 <span class="faint">변경 없음</span></h3><div class="body">${esc(a.original_text)}</div></div>
    <div class="pane"><h3>AI 교정본 <span class="faint"><del>삭제</del> <ins>추가</ins></span></h3><div class="body">${a._diff}</div></div>
    <div class="pane blogv"><h3>블로그 게시용 최종본 <span class="faint">${esc(a.hashtags || '')}</span></h3><div class="body"><b style="font-size:16px;display:block;margin-bottom:10px">${esc(KIT.title)}</b>${KIT.preview_html}</div></div></div>
    <p class="small muted mt">원문·메일 원본·교정본·게시본은 각각 따로 보존됩니다. 원문은 어떤 경우에도 덮어쓰지 않습니다.</p>`;
  } else if (AT.tab === 'edit') {
    const dis = a.status === 'published';
    el.innerHTML = `<div class="card"><label class="f">제목<input type="text" id="et" value="${esc(a.title)}" ${dis ? 'disabled' : ''}></label><label class="f mt">본문 (교정본 기준)<textarea id="ex" rows="22" ${dis ? 'disabled' : ''}>${esc(a.final_text || '')}</textarea></label>
    <div class="notice info mt"><span>저장하면 <b>원문 대비 숫자·날짜·기관명·인용문·누락 문장</b>을 다시 검사합니다. 달라진 항목은 확인 항목으로 표시됩니다. 수정본은 새 버전의 TXT로 따로 저장되며 기존 파일은 덮어쓰지 않습니다.</span></div>
    ${dis ? '<div class="notice warn mt">발행된 기사는 수정할 수 없습니다.</div>' : '<div class="row mt"><button class="btn pri" data-act="saveEdit">수정 저장</button></div>'}</div>`;
  } else if (AT.tab === 'flags') {
    el.innerHTML = `<div class="card"><h2>확인 항목</h2><div class="flags">${a.flags.length ? a.flags.map(f => flagHtml(f, true)).join('') : '<div class="muted">확인할 항목이 없습니다.</div>'}</div></div>
    <div class="card mt"><h2>교정 제안 <span class="faint small" style="font-weight:400">자동 적용하지 않고 사람이 판단합니다</span></h2>${a.suggestions.length ? `<table class="t"><tbody>${a.suggestions.map(s => `<tr><td class="small">${esc(s.rule)}</td><td><del>${esc(s.before)}</del> → <ins>${esc(s.after)}</ins></td><td class="muted small">${esc(s.context || '')}</td></tr>`).join('')}</tbody></table>` : '<div class="muted">제안 없음</div>'}</div>
    <div class="card mt"><h2>자동 적용된 교정 이력 <span class="badge">${a.corrections.length}</span></h2>${a.corrections.length ? `<table class="t"><thead><tr><th>규칙</th><th>변경</th><th>확신도</th></tr></thead><tbody>${a.corrections.map(c => `<tr><td class="small">${esc(c.rule)}</td><td><del>${esc(c.before)}</del> → <ins>${esc(c.after)}</ins></td><td class="small muted">${esc(c.confidence)}</td></tr>`).join('')}</tbody></table>` : '<div class="muted">자동으로 바뀐 부분이 없습니다.</div>'}</div>`;
  } else if (AT.tab === 'photos') {
    el.innerHTML = a.photo_list.length ? `<div class="photos">${a.photo_list.map((p, i) => `<div class="ph"><img class="im" loading="lazy" src="/files/thumb/${p.id}" data-act="zoom" data-id="${p.id}" alt="">${p.cover ? '<span class="cover">대표</span>' : ''}
      <div class="meta"><b title="${esc(p.name)}">${esc(p.name)}</b>${p.w}×${p.h} · ${bytes(p.size)}${p.ok ? '' : ' · <span style="color:var(--red)">열 수 없음</span>'}
      <input type="text" class="mt" style="padding:6px 9px;font-size:12.5px" placeholder="사진 설명(캡션)" value="${esc(p.caption)}" data-act-change="cap" data-id="${p.id}">
      <input type="text" style="padding:6px 9px;font-size:12.5px;margin-top:6px" placeholder="출처·촬영" value="${esc(p.credit)}" data-act-change="credit" data-id="${p.id}">
      <div class="row gap-s mt"><button class="btn sm" data-act="pmove" data-id="${p.id}" data-d="up" ${i === 0 ? 'disabled' : ''}>◀</button><button class="btn sm" data-act="pmove" data-id="${p.id}" data-d="down" ${i === a.photo_list.length - 1 ? 'disabled' : ''}>▶</button><button class="btn sm" data-act="pcover" data-id="${p.id}" ${p.cover ? 'disabled' : ''}>대표로</button></div></div></div>`).join('')}</div>
      <div class="notice info mt"><span>사진 설명은 직접 입력한 내용만 사용합니다. AI는 사진 내용을 추측해서 설명하지 않습니다.</span></div>` : `<div class="empty">${ic('image')}<div>첨부된 사진이 없는 기사입니다. 글만으로 완성됩니다.</div></div>`;
    $$('[data-act-change]').forEach(i => i.onchange = async () => { try { await api('/api/photos/' + i.dataset.id, { method: 'PATCH', body: { [i.dataset.actChange === 'cap' ? 'caption' : 'credit']: i.value } }); toast('저장했습니다.', 'ok'); } catch (e) { fail(e); } });
  } else if (AT.tab === 'publish') publishTab(el);
  else sourceTab(el);
}
function publishTab(el) {
  const a = CUR, k = KIT, ready = a.status === 'approved', done = a.status === 'published';
  el.innerHTML = `<div class="card"><div class="notice warn mb"><span><b>수동 보조 모드</b> — ${esc(k.auto_publish.reason)}</span></div>
  ${!ready && !done ? `<div class="notice bad mb"><span>먼저 위에서 <b>발행 승인</b>을 해야 게시 기록을 남길 수 있습니다. (미리 복사해 둘 수는 있습니다.)</span></div>` : ''}
  <ol class="steps">
   <li><div><b>제목 복사</b><div class="copybox mt row"><span class="grow">${esc(k.title)}</span><button class="btn sm" data-act="cpTitle">${ic('copy')} 복사</button></div></div></li>
   <li><div><b>본문 복사</b> <span class="muted small">사진 자리는 <span class="code">[사진 1]</span> 형태로 표시됩니다.</span><div class="row mt wrap"><button class="btn" data-act="cpHtml">${ic('copy')} 서식 포함 복사</button><button class="btn" data-act="cpPlain">${ic('copy')} 글자만 복사</button>${k.hashtags ? `<button class="btn" data-act="cpTags">${ic('copy')} 태그 복사</button>` : ''}</div>${k.hashtags ? `<div class="small muted mt">태그: ${esc(k.hashtags)}</div>` : ''}${k.category ? `<div class="small muted">카테고리: ${esc(k.category)}</div>` : ''}</div></li>
   <li><div><b>사진 내려받기</b> <span class="muted small">순서대로 편집기에 올리세요. 원본 화질 그대로입니다.</span>${k.photos.length ? `<div class="mt"><a class="btn" href="/api/articles/${a.id}/photos.zip">${ic('down')} 사진 ${k.photos.length}장 한 번에(ZIP)</a></div><div class="small mt muted">${k.photos.map(p => `사진 ${p.n}${p.cover ? '(대표)' : ''} — ${esc(p.name)}`).join('<br>')}</div>` : '<div class="muted mt">첨부 사진 없음</div>'}</div></li>
   <li><div><b>네이버 블로그 글쓰기 열기</b><div class="mt"><a class="btn amb" href="${esc(k.write_url)}" target="_blank" rel="noopener">${ic('ext')} 글쓰기 화면 열기</a> <span class="small muted">브라우저에서 네이버에 로그인된 상태여야 합니다.</span></div></div></li>
   <li><div><b>게시 후 주소 기록</b><div class="small muted">게시를 마친 글의 주소를 붙여 넣으면 ‘발행 완료’로 기록되고, 같은 기사는 다시 게시되지 않도록 잠깁니다.</div>
     ${done ? `<div class="notice ok mt"><span>이미 기록됨: ${esc(a.blog_url)}</span></div>` : `<div class="row mt"><input type="url" id="purl" placeholder="https://blog.naver.com/…/22…" ${ready || a.status === 'failed' ? '' : 'disabled'}><button class="btn pri" data-act="recPub" ${ready || a.status === 'failed' ? '' : 'disabled'}>발행 완료 기록</button></div><div class="row mt"><button class="btn sm danger" data-act="recFail" ${ready ? '' : 'disabled'}>게시에 실패했어요</button></div>`}</div></li></ol></div>`;
}
function sourceTab(el) {
  const a = CUR, m = a.mail;
  el.innerHTML = `<div class="grid g2"><div class="card"><h2>원본 이메일</h2><ul class="sys"><li><span class="k">제목</span><span class="v">${esc(m.subject)}</span></li><li><span class="k">발신</span><span class="v">${esc(m.sender_name)} &lt;${esc(m.sender_email)}&gt;</span></li><li><span class="k">수신</span><span class="v">${fmt(m.received_at, true)}</span></li><li><span class="k">원본 파일</span><span class="v"><a href="/files/mail/${m.id}">원본 메일(.eml) 내려받기</a></span></li></ul>
    <h2 class="mt">메일 본문</h2><div class="copybox small" style="white-space:pre-wrap;max-height:260px;overflow:auto">${esc(m.body || '(본문 없음)')}</div></div>
   <div class="card"><h2>첨부 문서</h2>${a.attachments.length ? `<table class="t"><tbody>${a.attachments.map(x => `<tr><td><a href="/files/att/${x.id}">${esc(x.name)}</a><div class="small muted">${bytes(x.size)}</div></td><td>${x.status === 'ok' ? '<span class="badge published">추출됨</span>' : x.status ? `<span class="badge failed" title="${esc(x.note)}">${x.status === 'manual' ? '수동 확인' : '추출 실패'}</span>` : ''}${x.note ? `<div class="small muted">${esc(x.note)}</div>` : ''}</td></tr>`).join('')}</tbody></table>` : '<div class="muted">첨부 문서 없음(메일 본문이 기사)</div>'}
   <h2 class="mt">분류 변경</h2><div class="row"><select id="rg" class="grow">${REGIONS_ORDER.map(r => `<option ${r === a.region ? 'selected' : ''}>${esc(r)}</option>`).join('')}</select></div>
   <label class="check mt"><input type="radio" name="rm" value="" checked><span>이 기사만 변경</span></label><label class="check"><input type="radio" name="rm" value="sender"><span>이 발신 주소의 메일은 앞으로 이 분류로</span></label><label class="check"><input type="radio" name="rm" value="domain"><span>이 도메인(@${esc((m.sender_email || '').split('@')[1] || '')})의 메일은 앞으로 이 분류로</span></label>
   <div class="row mt"><button class="btn pri" data-act="setRegion">분류 저장</button></div></div></div>`;
}

/* 기사 액션 */
ACT.approve = async () => {
  const a = CUR;
  try { await api(`/api/articles/${a.id}/approve`, { method: 'POST', body: {} }); toast('발행 대기로 이동했습니다. ‘게시 도우미’ 탭에서 게시하세요.', 'ok'); AT.tab = 'publish'; route(); }
  catch (e) {
    if (e.status !== 409) throw e;
    const bl = e.data.blockers || [];
    modal(`<h2 style="font-size:18px;margin-bottom:10px">발행 전에 확인이 필요합니다</h2><div class="flags">${bl.map(x => `<div class="flag block"><span class="m">${esc(x)}</span></div>`).join('')}</div>
      <p class="muted mt">항목을 확인해 ‘확인함’을 누르거나 내용을 수정한 뒤 다시 승인하세요.</p>
      ${e.data.can_override ? `<div class="card flat mt"><b>최고관리자 예외 승인</b><div class="small muted">사유가 활동 기록에 남습니다.</div><input type="text" id="ovr" class="mt" placeholder="예외 승인 사유(필수)"><button class="btn danger mt" id="ovb">그래도 승인</button></div>` : ''}
      <div class="row mt" style="justify-content:flex-end"><button class="btn" onclick="closeModal()">닫기</button></div>`, 'sm');
    const ob = $('#ovb'); if (ob) ob.onclick = async () => { try { await api(`/api/articles/${a.id}/approve`, { method: 'POST', body: { override: true, reason: $('#ovr').value } }); closeModal(); toast('예외 승인했습니다.', 'ok'); AT.tab = 'publish'; route(); } catch (er) { fail(er); } };
  }
};
ACT.unapprove = async () => { await api(`/api/articles/${CUR.id}/unapprove`, { method: 'POST', body: {} }); route(); };
ACT.exclude = async () => { const r = await promptBox('게시 제외', '제외 사유(선택)', '예: 홍보성 내용 / 중복 / 시의성 지남'); if (r === null) return; await api(`/api/articles/${CUR.id}/exclude`, { method: 'POST', body: { reason: r } }); route(); };
ACT.restore = async () => { await api(`/api/articles/${CUR.id}/restore`, { method: 'POST', body: {} }); route(); };
ACT.reproof = async () => { if (!await confirmBox('다시 교정할까요?', '수정해 둔 내용(수정본)은 사라지고 원문에서 다시 교정·초안 생성이 이루어집니다. 이전 버전의 TXT 파일은 그대로 남습니다.', '다시 교정')) return; await api(`/api/articles/${CUR.id}/reproofread`, { method: 'POST', body: {} }); toast('다시 교정했습니다.', 'ok'); route(); };
ACT.resolve = async el => { const n = await promptBox('확인 처리', '확인한 내용을 간단히 남겨 주세요(선택)', '예: 원문 PDF와 대조 완료'); if (n === null) return; await api(`/api/articles/${CUR.id}/flags/resolve`, { method: 'POST', body: { code: el.dataset.c, note: n } }); AT.tab = 'flags'; route(); };
ACT.saveEdit = async () => { await api(`/api/articles/${CUR.id}/edit`, { method: 'POST', body: { title: $('#et').value, text: $('#ex').value } }); toast('저장했습니다. 원문 대비 검사를 다시 실행했습니다.', 'ok'); AT.tab = 'compare'; route(); };
ACT.cpTitle = () => copyText(KIT.title);
ACT.cpHtml = () => copyText(KIT.plain, KIT.paste_html);
ACT.cpPlain = () => copyText(KIT.plain);
ACT.cpTags = () => copyText(KIT.hashtags);
ACT.recPub = async () => { await api(`/api/articles/${CUR.id}/published`, { method: 'POST', body: { url: $('#purl').value } }); toast('발행 완료로 기록했습니다.', 'ok'); route(); };
ACT.recFail = async () => { const r = await promptBox('게시 실패 기록', '실패 사유', '예: 네이버 편집기 오류'); if (r === null) return; await api(`/api/articles/${CUR.id}/failed`, { method: 'POST', body: { reason: r } }); route(); };
ACT.setRegion = async () => { const rm = $('input[name=rm]:checked').value; await api(`/api/articles/${CUR.id}/region`, { method: 'POST', body: { region: $('#rg').value, remember: rm } }); toast('분류를 저장했습니다.', 'ok'); route(); };
ACT.pmove = async el => { await api('/api/photos/' + el.dataset.id, { method: 'PATCH', body: { move: el.dataset.d } }); AT.tab = 'photos'; route(); };
ACT.pcover = async el => { await api('/api/photos/' + el.dataset.id, { method: 'PATCH', body: { cover: true } }); AT.tab = 'photos'; route(); };
ACT.zoom = el => { const p = (CUR && CUR.photo_list || []).find(x => x.id == el.dataset.id); modal(`<img src="/files/photo/${el.dataset.id}" style="max-width:100%;border-radius:10px;display:block;margin:auto"><div class="row mt between"><span class="muted small">${p ? esc(p.name) : ''}</span><a class="btn" href="/files/photo/${el.dataset.id}?dl=1">${ic('down')} 원본 내려받기</a></div>`); };

/* ───── 사진저장함 ───── */
const PH = { q: '', region: '전체', from: '', to: '', page: 1, sel: new Set(), un: false };
async function pPhotos(el) {
  const p = new URLSearchParams({ q: PH.q, region: PH.region, from: PH.from, to: PH.to, page: PH.page }); if (PH.un) p.set('unassigned', '1');
  const d = await api('/api/photos?' + p);
  el.innerHTML = `<div class="filters"><input type="search" id="phq" placeholder="기사 제목·기관·파일명 검색" value="${esc(PH.q)}"><select id="phr" style="width:170px">${['전체', ...REGIONS_ORDER].map(r => `<option ${r === PH.region ? 'selected' : ''}>${esc(r)}</option>`).join('')}</select>
    <input type="date" id="phf" value="${PH.from}" style="width:150px"><span class="muted">~</span><input type="date" id="pht" value="${PH.to}" style="width:150px"><label class="check"><input type="checkbox" id="phu" ${PH.un ? 'checked' : ''}>미배정만</label><button class="btn" data-act="phSearch">검색</button>
    <span class="right"></span><button class="btn pri" data-act="phZip" ${PH.sel.size ? '' : 'disabled'}>${ic('down')} 선택 ${PH.sel.size}장 일괄 다운로드</button></div>
    ${d.items.length ? `<div class="photos">${d.items.map(x => `<div class="ph"><img class="im" loading="lazy" src="/files/thumb/${x.id}" data-act="phOpen" data-id="${x.id}" alt=""><label class="sel"><input type="checkbox" data-act="phSel" data-id="${x.id}" ${PH.sel.has(x.id) ? 'checked' : ''}></label>
      <div class="meta"><b title="${esc(x.name)}">${esc(x.name)}</b>${x.article_title ? regBadge(x.region) : '<span class="badge failed">미배정</span>'} <span class="small">${fmt(x.received_at)}</span></div></div>`).join('')}</div>${pager(d.total, d.page, d.per, 'phPage')}` : `<div class="empty">${ic('image')}<div>저장된 사진이 없습니다.</div></div>`}`;
  el._items = d.items; $('#phq').onkeydown = e => { if (e.key === 'Enter') ACT.phSearch(); };
}
ACT.phSearch = () => { PH.q = $('#phq').value; PH.region = $('#phr').value; PH.from = $('#phf').value; PH.to = $('#pht').value; PH.un = $('#phu').checked; PH.page = 1; route(); };
ACT.phPage = el => { PH.page = +el.dataset.p; route(); };
ACT.phSel = el => { const id = +el.dataset.id; el.checked ? PH.sel.add(id) : PH.sel.delete(id); const b = $('[data-act=phZip]'); b.disabled = !PH.sel.size; b.innerHTML = `${ic('down')} 선택 ${PH.sel.size}장 일괄 다운로드`; };
ACT.phZip = async () => { await downloadPost('/api/photos/zip', { ids: [...PH.sel] }, 'PRESSFLOW_사진.zip'); };
ACT.phOpen = async el => {
  const it = ($('#page')._items || []).find(x => x.id == el.dataset.id); if (!it) return;
  modal(`<img src="/files/photo/${it.id}" style="max-width:100%;border-radius:10px;display:block;margin:auto"><div class="row mt wrap between"><div><b>${esc(it.name)}</b><div class="small muted">${it.w}×${it.h} · ${bytes(it.size)} · ${fmt(it.received_at, true)}</div></div>
   <div class="row"><a class="btn" href="/files/photo/${it.id}?dl=1">${ic('down')} 원본</a>${it.article_id ? `<a class="btn" href="#/article/${it.article_id}" onclick="closeModal()">기사 보기</a>` : ''}<a class="btn" href="/files/mail/${it.mail_id}">원본 메일</a></div></div>
   ${it.article_id ? '' : `<div class="notice warn mt"><span>이 사진은 어느 기사에 속하는지 확인되지 않았습니다. 기사 번호를 입력하면 기사 제목으로 이름이 바뀌어 연결됩니다.</span></div><div class="row mt"><input type="number" id="asg" placeholder="기사 번호(예: 12)" style="width:160px"><button class="btn pri" id="asb">기사에 연결</button></div>`}`);
  const b = $('#asb'); if (b) b.onclick = async () => { try { await api('/api/photos/' + it.id, { method: 'PATCH', body: { article_id: +$('#asg').value } }); closeModal(); toast('연결했습니다.', 'ok'); route(); } catch (e) { fail(e); } };
};

/* ───── 스타일 가이드 ───── */
async function pStyle(el) {
  const d = await api('/api/style'); const g = d.guide, an = d.analysis, adm = S.st.user.role === 'admin';
  const dis = adm ? '' : 'disabled';
  el.innerHTML = `<div class="notice ${g.status === 'confirmed' ? 'ok' : 'warn'} mb"><span>${g.status === 'confirmed' ? `<b>확정됨</b> — ${fmt(g.confirmed_at, true)} · ${esc(g.confirmed_by || '')}. 새로 처리되는 기사부터 이 규칙을 적용합니다.` : '<b>아직 확정되지 않았습니다.</b> 실제 블로그 게시물을 확인하기 전에는 특정 양식을 가정하지 않고 ‘기본형’으로 초안을 만듭니다.'}</span></div>
  <div class="grid g-main"><div class="col">
   <div class="card"><h2>1. 기존 블로그 분석 ${an ? `<span class="badge">${an.count}건 분석됨</span>` : ''}</h2><p class="muted small">공식 블로그의 최근 게시물(기본 30건)에서 제목 길이·말머리·말미 고정 문구·해시태그·사진 수를 찾아 <b>제안</b>합니다. 확정은 관리자가 합니다.</p>
    <div class="row wrap"><button class="btn pri" data-act="stRss" ${dis}>${ic('refresh')} 블로그에서 자동 분석</button><button class="btn" data-act="stPaste" ${dis}>대표 게시물 직접 붙여넣기</button></div>
    ${an ? `<ul class="mt" style="padding-left:18px;margin-bottom:0">${an.evidence.map(e => `<li class="small">${esc(e)}</li>`).join('')}</ul><div class="row mt"><button class="btn amb" data-act="stApply" ${dis}>분석 제안을 아래 양식에 채우기</button></div>` : ''}</div>
   <div class="card"><h2>2. 규칙 편집</h2><div class="grid g2">
    <label class="f">제목 앞 고정 말머리<input type="text" id="s_pre" value="${esc(g.title.prefix)}" ${dis} placeholder="예: [복지뉴스] "></label><label class="f">제목 뒤 고정 문구<input type="text" id="s_suf" value="${esc(g.title.suffix)}" ${dis}></label>
    <label class="f">제목 최대 길이(0=제한 없음)<input type="number" id="s_max" value="${g.title.max_len}" ${dis}></label><label class="check" style="align-self:end"><input type="checkbox" id="s_rb" ${g.title.region_bracket ? 'checked' : ''} ${dis}>시·군 기사는 제목 앞에 [지역] 붙이기</label></div>
    <label class="f mt">본문 첫머리 표기<small>{region} {org} {date} 사용 가능. 예: ({region}=강원사회복지신문)</small><input type="text" id="s_dl" value="${esc(g.body.dateline)}" ${dis}></label>
    <div class="grid g2 mt"><label class="f">사진 배치<select id="s_lay" ${dis}>${Object.entries(d.layouts).map(([k, v]) => `<option value="${k}" ${g.photos.layout === k ? 'selected' : ''}>${esc(v)}</option>`).join('')}</select></label><label class="f">사진 정렬<select id="s_al" ${dis}>${[['center', '가운데'], ['left', '왼쪽'], ['right', '오른쪽']].map(([k, v]) => `<option value="${k}" ${g.photos.align === k ? 'selected' : ''}>${v}</option>`).join('')}</select></label>
    <label class="f">캡션 형식<input type="text" id="s_cap" value="${esc(g.photos.caption_template)}" ${dis}></label><label class="f">출처 표기 형식<small>예: 사진=${'{credit}'}</small><input type="text" id="s_cr" value="${esc(g.photos.credit_template)}" ${dis}></label></div>
    <label class="check mt"><input type="checkbox" id="s_gap" ${g.body.paragraph_gap ? 'checked' : ''} ${dis}>문단 사이에 빈 줄 넣기</label><label class="check"><input type="checkbox" id="s_sc" ${g.photos.show_caption ? 'checked' : ''} ${dis}>사진 캡션 표시</label>
    <label class="f mt">기사 출처 줄<small>{org} 사용 가능. 예: 자료제공: {org}</small><input type="text" id="s_src" value="${esc(g.footer.source_line)}" ${dis}></label>
    <label class="f mt">기자명/신문사 표기<input type="text" id="s_rep" value="${esc(g.footer.reporter)}" ${dis} placeholder="예: 강원사회복지신문"></label>
    <label class="f mt">말미 고정 문구(여러 줄 가능)<textarea id="s_ft" rows="3" ${dis}>${esc(g.footer.text)}</textarea></label>
    <div class="grid g2 mt"><label class="f">카테고리<input type="text" id="s_cat" value="${esc(g.category)}" ${dis}></label><label class="check" style="align-self:end"><input type="checkbox" id="s_hte" ${g.hashtags.enabled ? 'checked' : ''} ${dis}>해시태그 사용</label></div>
    <label class="f mt">해시태그 (고정)<input type="text" id="s_ht" value="${esc(g.hashtags.fixed)}" ${dis} placeholder="#강원사회복지신문 #복지"></label>
    <div class="row mt">${adm ? `<button class="btn" data-act="stSave">저장</button><button class="btn pri" data-act="stConfirm">${ic('check')} 이 규칙으로 확정</button>${g.status === 'confirmed' ? '<button class="btn ghost" data-act="stUnconfirm">확정 해제</button>' : ''}` : '<span class="muted">최고관리자만 수정할 수 있습니다.</span>'}</div></div></div>
   <div class="card"><h2>적용 범위</h2><ul class="small" style="padding-left:18px"><li>확정 이후 <b>새로 수집·처리되는 기사</b>부터 적용됩니다.</li><li>이미 만든 초안은 기사 상세의 ‘다시 교정’으로 새 규칙에 맞춰 다시 만들 수 있습니다.</li><li>이미 블로그에 올라간 과거 게시물은 절대 자동 수정하지 않습니다.</li><li>사진 크기·세부 서식은 네이버 편집기에서 최종 조정합니다.</li></ul>${an && an.samples ? `<h2 class="mt">분석한 게시물</h2><div class="small muted" style="max-height:240px;overflow:auto">${an.samples.map(s => `<div style="padding:3px 0;border-bottom:1px dashed var(--line)">${s.link ? `<a href="${esc(s.link)}" target="_blank" rel="noopener">${esc(s.title)}</a>` : esc(s.title)}</div>`).join('')}</div>` : ''}</div></div>`;
  el._an = an;
}
function styleBody() { return { title: { prefix: $('#s_pre').value, suffix: $('#s_suf').value, max_len: +$('#s_max').value || 0, region_bracket: $('#s_rb').checked }, body: { dateline: $('#s_dl').value, paragraph_gap: $('#s_gap').checked }, photos: { layout: $('#s_lay').value, align: $('#s_al').value, caption_template: $('#s_cap').value, credit_template: $('#s_cr').value, show_caption: $('#s_sc').checked }, footer: { source_line: $('#s_src').value, reporter: $('#s_rep').value, text: $('#s_ft').value }, category: $('#s_cat').value, hashtags: { enabled: $('#s_hte').checked, fixed: $('#s_ht').value } }; }
ACT.stSave = async () => { await api('/api/style', { method: 'POST', body: styleBody() }); toast('저장했습니다.', 'ok'); route(); };
ACT.stConfirm = async () => { if (!await confirmBox('스타일 가이드를 확정할까요?', '앞으로 새로 처리되는 모든 기사 초안에 이 규칙이 적용됩니다. 과거 게시물은 바뀌지 않습니다.', '확정')) return; const r = await api('/api/style', { method: 'POST', body: { ...styleBody(), confirm: true } }); toast('확정했습니다. ' + r.note, 'ok'); route(); };
ACT.stUnconfirm = async () => { await api('/api/style', { method: 'POST', body: { unconfirm: true } }); route(); };
ACT.stRss = async el => { el.disabled = true; el.textContent = '분석 중…'; try { const r = await api('/api/style/analyze', { method: 'POST', body: { mode: 'rss', limit: 30 } }); toast(`${r.count}건 분석했습니다.`, 'ok'); } finally { route(); } };
ACT.stPaste = () => {
  modal(`<h2 style="font-size:18px">대표 게시물 붙여넣기</h2><p class="muted small">게시물마다 <b>첫 줄은 제목</b>, 나머지는 본문(해시태그 포함)으로 붙여 넣고, 게시물 사이는 <span class="code">=====</span> 한 줄로 구분하세요.</p><textarea id="pst" rows="16" placeholder="[원주시] 취약계층 복지지원 확대&#10;본문…&#10;#강원사회복지신문&#10;=====&#10;다음 게시물 제목&#10;본문…"></textarea><div class="row mt" style="justify-content:flex-end"><button class="btn" onclick="closeModal()">취소</button><button class="btn pri" id="pgo">분석</button></div>`);
  $('#pgo').onclick = async () => { try { const r = await api('/api/style/analyze', { method: 'POST', body: { mode: 'paste', text: $('#pst').value } }); closeModal(); toast(`${r.count}건 분석했습니다.`, 'ok'); route(); } catch (e) { fail(e); } };
};
ACT.stApply = () => {
  const an = $('#page')._an; if (!an) return; const p = an.proposal || {};
  const set = (id, v) => { const e = $(id); if (e && v !== undefined) { if (e.type === 'checkbox') e.checked = !!v; else e.value = v; } };
  set('#s_pre', (p.title || {}).prefix); set('#s_rb', (p.title || {}).region_bracket); set('#s_dl', (p.body || {}).dateline); set('#s_ft', (p.footer || {}).text);
  set('#s_hte', (p.hashtags || {}).enabled); set('#s_ht', (p.hashtags || {}).fixed); set('#s_cat', p.category);
  toast('제안을 채웠습니다. 검토 후 ‘확정’을 눌러 주세요.', 'ok');
};

/* ───── 백업 ───── */
async function pBackup(el) {
  const d = await api('/api/backups'), adm = S.st.user.role === 'admin';
  const lab = { files: '6시간 증분(파일)', db: '매일 데이터베이스', full: '매주 전체' };
  el.innerHTML = `${d.same_drive ? `<div class="notice warn mb"><span><b>백업이 데이터와 같은 드라이브에 있습니다.</b> 디스크가 고장 나면 함께 사라집니다. 설정에서 다른 드라이브·외장하드·클라우드 동기화 폴더로 바꾸세요.</span></div>` : ''}
  <div class="grid g3">${['files', 'db', 'full'].map(k => { const l = d.last[k]; return `<div class="card"><div class="muted small">${lab[k]}</div><div class="row mt">${l ? `<span class="dot ${l.ok ? 'ok' : 'bad'}"></span><b>${ago(l.at)}</b>` : '<span class="dot"></span><span class="muted">아직 없음</span>'}</div>${l && !l.ok ? `<div class="small mt" style="color:var(--red)">${esc(l.detail)}</div>` : ''}${adm ? `<button class="btn sm mt" data-act="bkRun" data-k="${k}">지금 실행</button>` : ''}</div>`; }).join('')}</div>
  <div class="grid g-main mt"><div class="card"><h2>백업 목록 <span class="faint small" style="font-weight:400">${esc(d.dir)}</span></h2>${d.items.length ? `<table class="t"><thead><tr><th>종류</th><th>이름</th><th>크기</th><th>시각</th></tr></thead><tbody>${d.items.map(i => `<tr><td><span class="badge">${{ db: 'DB', full: '전체', files: '증분' }[i.kind]}</span></td><td class="small mono">${esc(i.name)}${i.count ? ` · 파일 ${i.count}개` : ''}</td><td class="small">${bytes(i.size)}</td><td class="small muted">${fmt(i.at, true)}</td></tr>`).join('')}</tbody></table>` : '<div class="empty">아직 백업이 없습니다. 설정 완료 후 자동으로 만들어집니다.</div>'}</div>
  <div class="col"><div class="card"><h2>복구 테스트</h2>${d.restore_test ? `<div class="row"><span class="dot ${d.restore_test.ok ? 'ok' : 'bad'}"></span><b>${d.restore_test.ok ? '성공' : '실패'}</b><span class="muted small">${ago(d.restore_test.at)}</span></div><ul class="small" style="padding-left:18px">${d.restore_test.detail.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : '<div class="muted">아직 실행하지 않았습니다.</div>'}${adm ? `<button class="btn mt" data-act="bkVerify">지금 복구 테스트</button>` : ''}<div class="small muted mt">최신 DB·전체 백업을 실제로 복호화해 열어 보고 무결성을 검사합니다. 매주 자동으로도 실행됩니다.</div></div>
  <div class="card"><h2>보존 규칙</h2><ul class="small" style="padding-left:18px;margin:0"><li>6시간마다 새로 바뀐 파일만 증분 백업</li><li>매일 DB, 매주 전체 백업, 기능 업데이트 전 백업</li><li>최소 30일 보관, 모두 암호화</li><li>앱 업데이트는 기존 DB를 지우거나 초기화하지 않음</li></ul></div></div></div>`;
}
ACT.bkRun = async el => { await api('/api/backups/run', { method: 'POST', body: { kind: el.dataset.k } }); toast('백업을 시작했습니다. 잠시 후 새로고침하세요.', 'ok'); setTimeout(route, 4000); };
ACT.bkVerify = async el => { el.disabled = true; el.textContent = '검사 중…'; const r = await api('/api/backups/verify', { method: 'POST', body: {} }); toast(r.ok ? '복구 테스트 성공' : '복구 테스트 실패', r.ok ? 'ok' : 'bad'); route(); };

/* ───── 설정 ───── */
const ST = { tab: 'mail' };
async function pSettings(el, q) {
  if (q.tab) ST.tab = q.tab;
  const s = await api('/api/settings'), adm = S.st.user.role === 'admin';
  const tabs = [['mail', '네이버 메일'], ['blog', '블로그'], ['ai', 'AI 교정'], ['rules', '분류 규칙'], ['dict', '교정 표기 사전'], ['backup', '백업 위치'], ['update', '업데이트'], ['users', '사용자'], ['me', '내 계정']];
  el.innerHTML = `<div class="tabs">${tabs.map(t => `<button class="${ST.tab === t[0] ? 'on' : ''}" data-act="stTab" data-t="${t[0]}">${t[1]}</button>`).join('')}</div><div id="st-body" style="max-width:760px"></div>`;
  const b = $('#st-body');
  if (!adm && !['me'].includes(ST.tab)) { b.innerHTML = '<div class="notice info">최고관리자만 변경할 수 있는 설정입니다.</div>'; return; }
  if (ST.tab === 'mail') {
    b.innerHTML = `<div class="card col"><label class="f">네이버 아이디<input type="text" id="mu" value="${esc(s.mail.user)}"></label><label class="f">비밀번호 / 애플리케이션 비밀번호<small>${s.mail.has_password ? '저장되어 있습니다. 바꿀 때만 입력하세요.' : '입력하세요.'}</small><input type="password" id="mp" autocomplete="off"></label>
    <div class="grid g2"><label class="f">자동 수집 주기(분)<input type="number" id="mm" value="${s.mail.minutes}" min="5"></label><label class="f">최초 수집 범위(일)<small>연결 시점 기준</small><input type="number" id="mi" value="${s.mail.initial_days}"></label></div>
    <label class="check"><input type="checkbox" id="ma" ${s.mail.auto ? 'checked' : ''}>자동 수집 사용</label><div class="row"><button class="btn" data-act="mTest">연결 테스트</button><span id="mtr" class="small"></span></div><div class="row"><button class="btn pri" data-act="mSave">저장</button></div>
    <div class="notice info"><span>메일은 읽기 전용으로 열며 삭제·이동·읽음 표시를 하지 않습니다. 컴퓨터가 꺼져 있는 동안 도착한 메일은 켜질 때 이어서 수집합니다.</span></div></div>`;
  } else if (ST.tab === 'blog') {
    b.innerHTML = `<div class="card col"><label class="f">공식 블로그 주소<input type="text" id="bu" value="${esc(s.blog.url)}" placeholder="https://blog.naver.com/…"></label><div class="row"><button class="btn pri" data-act="bSave">저장</button>${s.blog.id ? `<a class="btn" href="${esc(s.blog.write_url)}" target="_blank" rel="noopener">${ic('ext')} 글쓰기 열기</a>` : ''}</div>
    <div class="notice warn"><span><b>게시 방식: 수동 보조.</b> 네이버가 블로그 글쓰기 API를 종료해, 로그인 정보를 받지 않고 완성된 기사·사진을 편집기에 옮기는 도우미를 제공합니다. 자동 발행은 네이버가 허용하는 공식 방법이 확인되기 전까지 켜지 않으며, 켜진 것처럼 표시하지도 않습니다.</span></div></div>`;
  } else if (ST.tab === 'ai') {
    b.innerHTML = `<div class="card col"><label class="check"><input type="checkbox" id="ae" ${s.ai.enabled ? 'checked' : ''}><span>AI(Claude) 교정 사용 <small class="muted" style="display:block;font-weight:400">켜면 기사 본문이 Anthropic API로 전송됩니다. 끄면 이 컴퓨터 안의 규칙 기반 교정만 사용합니다.</small></span></label>
    <label class="f">API 키<small>${s.ai.has_key ? '저장되어 있습니다. 바꿀 때만 입력.' : '필요합니다.'}</small><input type="password" id="ak" autocomplete="off"></label><label class="f">모델<input type="text" id="am" value="${esc(s.ai.model)}"></label>
    <div class="row"><button class="btn pri" data-act="aSave">저장</button><button class="btn" data-act="aTest">연결 테스트</button><span id="atr" class="small"></span></div>
    <div class="notice info"><span>AI가 만든 교정본은 원문과 대조해 <b>숫자·날짜·기관명·인용문·누락 문장</b>이 하나라도 달라지면 채택하지 않고 규칙 기반 결과를 씁니다.</span></div></div>`;
  } else if (ST.tab === 'rules') {
    const r = await api('/api/rules');
    b.innerHTML = `<div class="card"><p class="muted small">발신 주소·도메인별 분류 규칙입니다. 규칙은 이름 기반 자동 분류보다 먼저 적용됩니다. 기사 상세에서 분류를 바꿀 때 ‘앞으로도’를 선택하면 자동으로 추가됩니다.</p>
    <div class="row mb wrap"><select id="rk" style="width:120px"><option value="domain">도메인</option><option value="sender">발신 주소</option></select><input type="text" id="rp" placeholder="예: wonju.go.kr" style="flex:1;min-width:160px"><select id="rr" style="width:170px">${REGIONS_ORDER.map(x => `<option>${esc(x)}</option>`).join('')}</select><button class="btn pri" data-act="ruleAdd">추가</button></div>
    ${r.rules.length ? `<table class="t"><tbody>${r.rules.map(x => `<tr><td><span class="badge">${x.kind === 'domain' ? '도메인' : '주소'}</span></td><td class="mono">${esc(x.pattern)}</td><td>${regBadge(x.region)}</td><td><button class="btn sm danger" data-act="ruleDel" data-id="${x.id}">삭제</button></td></tr>`).join('')}</tbody></table>` : '<div class="muted">저장된 규칙이 없습니다.</div>'}</div>`;
  } else if (ST.tab === 'dict') {
    const rows = Object.entries(s.proof_dict).map(([k, v]) => `${k} => ${v}`).join('\n');
    b.innerHTML = `<div class="card col"><p class="muted small">한 줄에 하나씩 <span class="code">틀린 표기 => 바른 표기</span> 형식으로 적습니다. 신문사 표기 원칙(예: ‘복지서비스’를 붙여 쓸지)에 맞게 직접 정하세요. 이 사전은 새로 처리하는 기사부터 적용됩니다.</p><textarea id="dc" rows="12">${esc(rows)}</textarea><div class="row"><button class="btn pri" data-act="dSave">저장</button></div></div>`;
  } else if (ST.tab === 'backup') {
    b.innerHTML = `<div class="card col"><label class="f">백업 저장 폴더<small>다른 드라이브·외장하드·NAS·클라우드 동기화 폴더 권장</small><input type="text" id="bd" value="${esc(s.backup.dir)}"></label>
    <div class="grid g2"><label class="f">보관 기간(일, 최소 30)<input type="number" id="br" min="30" value="${s.backup.retention_days}"></label><label class="check" style="align-self:end"><input type="checkbox" id="ba" ${s.backup.auto ? 'checked' : ''}>자동 백업 사용</label></div>
    <div class="row"><button class="btn pri" data-act="bkSave">저장</button><button class="btn" data-act="showKey">복구 키 보기</button></div><div class="small muted">데이터 폴더: <span class="code">${esc(s.data_dir)}</span></div></div>`;
  } else if (ST.tab === 'update') {
    const u = await api('/api/update'), l = u.last || {};
    b.innerHTML = `<div class="card col">
    <div class="row" style="justify-content:space-between"><div><div class="small muted">현재 버전</div><div style="font-size:22px;font-weight:700">${esc(u.current)}</div></div>
    <div style="text-align:right"><div class="small muted">최근 확인</div><div>${l.checked ? fmt(l.checked, true) : '아직 확인 전'}</div></div></div>
    ${u.rolled_back ? `<div class="notice warn"><span><b>새 버전(${esc(u.rolled_back.from || '')})이 시작되지 않아 이전 버전(${esc(u.rolled_back.to || '')})으로 자동 복귀했습니다.</b> 자료는 그대로입니다. 배포 담당자에게 알려 주세요. <a href="#" data-act="rbAck">확인했습니다</a></span></div>` : ''}
    ${l.available ? `<div class="notice ok"><span><b>새 버전 ${esc(l.latest)} 이(가) 있습니다.</b> ${esc(l.notes || '')}</span></div><div class="row"><button class="btn pri" data-act="updApply">지금 업데이트</button></div>`
      : l.error ? `<div class="notice warn"><span>확인 실패: ${esc(l.error)}</span></div>` : u.url ? '<div class="notice info"><span>최신 버전을 사용 중입니다.</span></div>' : ''}
    ${u.has_key ? '' : '<div class="notice warn"><span>이 프로그램에는 업데이트 서명 키가 없어 자동 업데이트를 쓸 수 없습니다. 배포 담당자에게 업데이트가 설정된 설치본을 받으세요.</span></div>'}
    <label class="f">업데이트 확인 주소<small>배포 담당자가 알려 준 주소입니다(웹 주소 또는 공유 폴더의 latest.json). 비워 두면 기본 주소를 씁니다${u.default_url ? ': ' + esc(u.default_url) : ''}.</small><input type="text" id="uu" value="${esc(u.url === u.default_url ? '' : u.url)}" placeholder="${esc(u.default_url || 'https://…/latest.json')}"></label>
    <label class="check"><input type="checkbox" id="ua" ${u.auto ? 'checked' : ''}><span>새 버전을 자동으로 설치 <small class="muted" style="display:block;font-weight:400">수집·백업 중이 아니고 10분 이상 화면을 쓰지 않을 때만 설치하고 자동으로 다시 시작합니다. 설치 전에 데이터를 백업합니다.</small></span></label>
    <div class="row"><button class="btn pri" data-act="updSave">저장</button><button class="btn" data-act="updCheck">지금 확인</button></div>
    <div class="notice info"><span>업데이트는 <b>배포 담당자의 전자서명이 맞을 때만</b> 설치됩니다. 수집한 자료·설정은 업데이트로 지워지지 않으며, 새 버전이 시작되지 않으면 이전 버전으로 자동 복귀합니다.</span></div></div>`;
  } else if (ST.tab === 'users') {
    const u = await api('/api/users');
    b.innerHTML = `<div class="card"><table class="t"><thead><tr><th>이름</th><th>아이디</th><th>권한</th><th></th></tr></thead><tbody>${u.users.map(x => `<tr><td>${esc(x.display)}</td><td class="mono">${esc(x.username)}</td><td>${x.role === 'admin' ? '최고관리자' : '편집자'}</td><td>${x.active ? `<button class="btn sm" data-act="uTog" data-id="${x.id}" data-a="0">비활성화</button>` : `<button class="btn sm" data-act="uTog" data-id="${x.id}" data-a="1">활성화</button>`} <button class="btn sm" data-act="uPw" data-id="${x.id}">비밀번호 재설정</button></td></tr>`).join('')}</tbody></table>
    <h2 class="mt-l">직원 계정 추가</h2><div class="grid g2"><label class="f">표시 이름<input type="text" id="nd"></label><label class="f">아이디<input type="text" id="nu"></label><label class="f">비밀번호(8자 이상)<input type="password" id="np"></label><label class="f">권한<select id="nr"><option value="editor">편집자</option><option value="admin">최고관리자</option></select></label></div><div class="row mt"><button class="btn pri" data-act="uAdd">추가</button></div>
    <div class="small muted mt">편집자: 자료 열람·교정본 검수·사진·블로그 기사 수정·발행 승인(차단 항목이 없을 때). 최고관리자: 설정·연동·스타일 확정·백업·사용자·차단 항목 예외 승인.</div></div>`;
  } else {
    b.innerHTML = `<div class="card col"><label class="f">현재 비밀번호<input type="password" id="o"></label><label class="f">새 비밀번호(8자 이상)<input type="password" id="n"></label><div class="row"><button class="btn pri" data-act="pwSave">비밀번호 변경</button></div></div>`;
  }
}
ACT.stTab = el => { ST.tab = el.dataset.t; route(); };
ACT.mTest = async () => { const r = await api('/api/mail/test', { method: 'POST', body: { user: $('#mu').value, password: $('#mp').value } }); $('#mtr').innerHTML = r.ok ? `<span style="color:var(--green)">✔ 연결 성공 (받은편지함 ${r.total}통)</span>` : `<span style="color:var(--red)">${esc(r.error)}</span>`; };
ACT.mSave = async () => { await api('/api/settings/mail', { method: 'POST', body: { user: $('#mu').value, password: $('#mp').value, minutes: +$('#mm').value, initial_days: +$('#mi').value, auto: $('#ma').checked } }); S.st = await api('/api/state'); toast('저장했습니다.', 'ok'); route(); };
ACT.bSave = async () => { await api('/api/settings/blog', { method: 'POST', body: { url: $('#bu').value } }); S.st = await api('/api/state'); toast('저장했습니다.', 'ok'); route(); };
ACT.aSave = async () => { await api('/api/settings/ai', { method: 'POST', body: { enabled: $('#ae').checked, key: $('#ak').value, model: $('#am').value } }); toast('저장했습니다.', 'ok'); route(); };
ACT.aTest = async () => { $('#atr').textContent = '확인 중…'; const r = await api('/api/ai/test', { method: 'POST', body: {} }); $('#atr').innerHTML = r.ok ? '<span style="color:var(--green)">✔ 연결 성공</span>' : `<span style="color:var(--red)">${esc(r.error)}</span>`; };
ACT.ruleAdd = async () => { await api('/api/rules', { method: 'POST', body: { kind: $('#rk').value, pattern: $('#rp').value, region: $('#rr').value } }); route(); };
ACT.ruleDel = async el => { await api('/api/rules/' + el.dataset.id, { method: 'DELETE', body: {} }); route(); };
ACT.dSave = async () => { const d = {}; $('#dc').value.split('\n').forEach(l => { const m = l.split('=>'); if (m.length === 2 && m[0].trim() && m[1].trim()) d[m[0].trim()] = m[1].trim(); }); await api('/api/proof-dict', { method: 'POST', body: { dict: d } }); toast('저장했습니다.', 'ok'); };
ACT.bkSave = async () => { const r = await api('/api/settings/backup', { method: 'POST', body: { dir: $('#bd').value, auto: $('#ba').checked, retention_days: +$('#br').value } }); toast(r.same_drive ? '저장했습니다. (데이터와 같은 드라이브입니다)' : '저장했습니다.', r.same_drive ? '' : 'ok'); };
ACT.showKey = async () => { const k = await api('/api/recovery-key'); modal(`<h2 style="font-size:18px;margin-bottom:8px">복구 키</h2><p class="muted small">이 키가 있어야 다른 컴퓨터에서 백업을 열 수 있습니다. 조회 기록이 남습니다.</p><div class="keybox">${esc(k.key)}</div><div class="row mt" style="justify-content:flex-end"><button class="btn" onclick="closeModal()">닫기</button></div>`, 'sm'); };
ACT.updSave = async () => { await api('/api/update/settings', { method: 'POST', body: { url: $('#uu').value, auto: $('#ua').checked } }); toast('저장했습니다.', 'ok'); route(); };
ACT.updCheck = async el => { el.disabled = true; el.textContent = '확인 중…'; const r = await api('/api/update/check', { method: 'POST', body: {} }); toast(r.error ? '확인 실패: ' + r.error : r.available ? '새 버전 ' + r.latest + ' 이(가) 있습니다.' : '최신 버전입니다.', r.error ? 'bad' : 'ok'); route(); };
ACT.rbAck = async () => { await api('/api/update/ack-rollback', { method: 'POST', body: {} }); route(); };
ACT.updApply = async el => {
  if (!await confirmBox('업데이트하고 다시 시작할까요?', '설치 전에 데이터를 자동 백업합니다. 1~2분 걸릴 수 있습니다.', '업데이트')) return;
  el.disabled = true; el.textContent = '설치 중…(백업 포함, 1~2분)';
  try {
    const r = await api('/api/update/apply', { method: 'POST', body: {} });
    if (!r.updated) { toast(r.message, 'ok'); route(); return; }
    modal('<div style="padding:18px;text-align:center"><div class="upd-spin"></div><h2 style="font-size:18px;margin:12px 0 4px">업데이트 중입니다</h2><p class="muted small">잠시 후 자동으로 새 버전이 열립니다.</p></div>', 'sm');
    const t0 = Date.now();
    const poll = async () => { try { const h = await fetch('/api/health', { cache: 'no-store' }); const d = await h.json(); if (d.version === r.to) { location.reload(); return; } } catch (e) {} if (Date.now() - t0 > 90000) { location.reload(); return; } setTimeout(poll, 1500); };
    setTimeout(poll, 3000);
  } catch (er) { fail(er); el.disabled = false; el.textContent = '지금 업데이트'; }
};
ACT.uAdd = async () => { await api('/api/users', { method: 'POST', body: { display: $('#nd').value, username: $('#nu').value, password: $('#np').value, role: $('#nr').value } }); toast('추가했습니다.', 'ok'); route(); };
ACT.uTog = async el => { await api('/api/users/' + el.dataset.id, { method: 'PATCH', body: { active: el.dataset.a === '1' } }); route(); };
ACT.uPw = async el => { const p = await promptBox('비밀번호 재설정', '새 비밀번호(8자 이상)'); if (!p) return; await api('/api/users/' + el.dataset.id, { method: 'PATCH', body: { password: p } }); toast('변경했습니다.', 'ok'); };
ACT.pwSave = async () => { await api('/api/password', { method: 'POST', body: { old: $('#o').value, new: $('#n').value } }); toast('변경했습니다.', 'ok'); $('#o').value = $('#n').value = ''; };

/* ───── 활동 기록 ───── */
async function pAudit(el) {
  const d = await api('/api/audit');
  el.innerHTML = `<div class="card" style="padding:6px 10px"><table class="t"><thead><tr><th>시각</th><th>사용자</th><th>작업</th><th>내용</th></tr></thead><tbody>${d.items.map(i => `<tr><td class="small mono muted">${fmt(i.ts, true)}</td><td>${esc(i.user)}</td><td><b>${esc(i.action)}</b></td><td class="small muted">${esc(i.detail)}</td></tr>`).join('')}</tbody></table></div>`;
}

boot();
