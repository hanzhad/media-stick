"""The «Язык» part of the page: the row of the settings list, the page of languages, its style and script, as strings.
inject() (panel_lang.py) puts them at the page's three @@LANG_...@@ markers. Everything is prefixed `lg` / `lg-` so it
cannot collide with the page's own names. Text goes in with textContent.

The page is a search field and a short list (the current language, the usual four); the whole list opens in place from
one row. Typing filters by the start of any word of the native, Russian or English name or the code, ignoring case and
diacritics."""

ROW = """<button class="srow" data-sp="lang"><svg class="i"><use href="#i-text"/></svg><span class="sname">Язык</span><span class="sval" id="sv-lang"></span><span class="chev" aria-hidden="true">›</span></button>
      """

SECTION = """<section id="t-lang" data-tab="settings" data-spage="lang" class="hide">
    <h2 class="lg-title">Язык</h2>
    <div class="lg-sr"><input id="lg-q" type="search" placeholder="Найти язык" aria-label="Найти язык" autocomplete="off" autocorrect="off" autocapitalize="off" spellcheck="false" enterkeyhint="go"><button id="lg-x" type="button" class="lg-x" aria-label="Очистить" hidden>✕</button></div>
    <div id="lg-list"></div>
    <p class="lg-note">Язык для YouTube и SWEET.TV на ТВ. Интерфейс самой приставки и этой страницы пока остаются прежними.</p>
  </section>"""

# @@LANGS@@ is filled in with the table (panel_lang.py): [{code, name, ru, en}], in the order shown
TAIL = r"""
<style>
.lg-title{margin:0 6px 14px;font-size:24px;font-weight:600;letter-spacing:0;text-transform:none;color:inherit}
.lg-sr{position:relative;margin:0 0 14px}
#lg-q{width:100%;box-sizing:border-box;min-height:48px;padding:0 44px 0 16px;border:0;border-radius:14px;background:var(--card);color:inherit;font:inherit;font-size:16px;-webkit-appearance:none;appearance:none;outline:none}
#lg-q::placeholder{color:var(--faint)}
#lg-q::-webkit-search-cancel-button{-webkit-appearance:none;display:none}
.lg-x{position:absolute;right:0;top:0;width:48px;height:48px;background:none;border:0;color:var(--dim);font-size:16px}
.lg-rows{background:var(--card);border-radius:20px;overflow:hidden;margin:0 0 14px}
.lg-h{margin:18px 6px 8px;color:var(--dim);font-size:13px;letter-spacing:.04em;text-transform:uppercase}
.lg-row{display:flex;align-items:center;gap:12px;width:100%;min-height:56px;padding:8px 16px;background:none;border:0;border-top:1px solid var(--line);color:inherit;font:inherit;font-size:17px;text-align:left;touch-action:manipulation}
.lg-row:first-child{border-top:0}
.lg-row:active{background:var(--card2)}
.lg-tx{flex:1 1 0;min-width:0}
.lg-tx b{display:block;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lg-tx small{display:block;margin-top:1px;color:var(--dim);font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lg-ck{flex:none;display:flex;color:var(--ok)}
.lg-more{color:var(--dim)}
.lg-none{margin:14px 6px;color:var(--dim);font-size:15px}
.lg-note{margin:8px 6px 0;color:var(--faint);font-size:13px;line-height:1.4}
@media (min-width:900px){#t-lang{grid-area:lang;max-width:480px}}
</style>
<script>
// ---- the language of the device: search, a short list, the whole list on one tap ----
const LG=@@LANGS@@;
const LG_TICK='<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
const LG_POP=['ru','uk','en','en_US'];
let lgCur='', lgAll=false;
// case and diacritics do not matter: «cest» finds Čeština
const lgNorm=s=>String(s).normalize('NFD').replace(/\p{M}/gu,'').toLowerCase();
LG.forEach(l=>{l.k=lgNorm([l.name,l.ru,l.en,l.code.replace('_',' ')].join(' ')).split(/[\s()._-]+/).filter(Boolean).concat(lgNorm(l.code))});
const lgName=c=>{const l=LG.find(x=>x.code===c);return l?l.name:''};
// every word typed must start some word of the names or the code
function lgMatches(){
  const t=lgNorm($('lg-q').value).split(/\s+/).filter(Boolean);
  return t.length?LG.filter(l=>t.every(w=>l.k.some(k=>k.startsWith(w)))):[]
}
function lgRow(l){
  const b=document.createElement('button'), t=document.createElement('span'), n=document.createElement('b');
  b.type='button';b.className='lg-row';t.className='lg-tx';n.textContent=l.name;t.append(n);
  if(l.ru&&lgNorm(l.ru)!==lgNorm(l.name)){const s=document.createElement('small');s.textContent=l.ru;t.append(s)}   // the Russian name, unless it only repeats
  b.append(t);
  if(l.code===lgCur){const k=document.createElement('span');k.className='lg-ck';k.innerHTML=LG_TICK;b.append(k);b.setAttribute('aria-current','true')}
  b.onclick=()=>lgPick(l);return b
}
function lgMore(open){
  const b=document.createElement('button');b.type='button';b.className='lg-row lg-more';
  b.textContent='Все языки · '+LG.length+(open?' ‹':' ›');b.onclick=()=>{lgAll=!open;lgDraw()};return b
}
function lgDraw(){
  const box=$('lg-list');box.textContent='';
  const q=$('lg-q').value.trim();$('lg-x').hidden=!q;
  const group=rows=>{const g=document.createElement('div');g.className='lg-rows';rows.forEach(r=>g.append(r));box.append(g)};
  if(q){
    const m=lgMatches();
    if(m.length)group(m.map(lgRow));
    else{const p=document.createElement('p');p.className='lg-none';p.textContent='Ничего не нашлось';box.append(p)}
    return
  }
  if(lgAll){group([lgMore(true)].concat(LG.map(lgRow)));return}
  const cur=LG.find(l=>l.code===lgCur);
  if(cur)group([lgRow(cur)]);
  const h=document.createElement('div');h.className='lg-h';h.textContent='Часто выбирают';box.append(h);
  group(LG_POP.filter(c=>c!==lgCur).map(c=>LG.find(l=>l.code===c)).map(lgRow));
  group([lgMore(false)])
}
// the state of the «Язык» row; the status carries the code (the page redraws when it changes elsewhere)
function langRowText(s){
  const c=s&&s.lang;
  if(c&&c!==lgCur){lgCur=c;lgDraw()}
  return lgName(lgCur)
}
function lgReset(){$('lg-q').value='';lgAll=false;lgDraw()}
async function lgPick(l){
  buzz();
  if(l.code===lgCur){lgReset();return}
  try{await api('/api/lang',{code:l.code});lgCur=l.code;lgReset();if(window.setRows)setRows();toast('Язык: '+l.name)}
  catch(e){toast('Не получилось: '+tvErr(e))}
}
$('lg-q').addEventListener('input',lgDraw);
$('lg-q').addEventListener('keydown',e=>{
  if(e.key==='Enter'){e.preventDefault();const m=lgMatches();if(m.length)lgPick(m[0])}
  else if(e.key==='Escape'){e.preventDefault();lgReset()}
});
$('lg-x').onclick=()=>{lgReset();$('lg-q').focus()};
lgDraw();
</script>
"""
