"""The «Язык» part of the page: the row of the settings list, the page of languages, its style and script, as strings.
inject() (panel_lang.py) puts them at the page's three @@LANG_...@@ markers. Everything is prefixed `lg` / `lg-` so it
cannot collide with the page's own names. Text goes in with textContent."""

ROW = """<button class="srow" data-sp="lang"><svg class="i"><use href="#i-text"/></svg><span class="sname">Язык</span><span class="sval" id="sv-lang"></span><span class="chev" aria-hidden="true">›</span></button>
      """

SECTION = """<section id="t-lang" data-tab="settings" data-spage="lang" class="hide">
    <h2 class="lg-title">Язык</h2>
    <div id="lg-list" class="lg-rows"></div>
    <p class="lg-note">Язык для YouTube и SWEET.TV на ТВ. Интерфейс самой приставки и этой страницы пока остаются прежними.</p>
  </section>"""

# @@LANGS@@ is filled in with the table (panel_lang.py): [{code, name}], in the order shown
TAIL = r"""
<style>
.lg-title{margin:0 6px 14px;font-size:24px;font-weight:600;letter-spacing:0;text-transform:none;color:inherit}
.lg-rows{background:var(--card);border-radius:20px;overflow:hidden}
.lg-row{display:flex;align-items:center;gap:12px;width:100%;min-height:52px;padding:8px 16px;background:none;border:0;border-top:1px solid var(--line);color:inherit;font:inherit;font-size:17px;text-align:left;touch-action:manipulation}
.lg-row:first-child{border-top:0}
.lg-row:active{background:var(--card2)}
.lg-name{flex:1 1 0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.lg-ck{flex:none;display:flex;color:var(--ok)}
.lg-note{margin:8px 6px 0;color:var(--faint);font-size:13px;line-height:1.4}
@media (min-width:900px){#t-lang{grid-area:lang}}
</style>
<script>
// ---- the language of the device: a list of names in their own language, a check on the current one ----
const LG=@@LANGS@@;
const LG_TICK='<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
let lgCur='';
const lgName=c=>{const l=LG.find(x=>x.code===c);return l?l.name:''};
function lgDraw(){
  const box=$('lg-list');box.textContent='';
  LG.forEach(l=>{
    const b=document.createElement('button'), n=document.createElement('span');
    b.type='button';b.className='lg-row';n.className='lg-name';n.textContent=l.name;b.append(n);
    if(l.code===lgCur){const k=document.createElement('span');k.className='lg-ck';k.innerHTML=LG_TICK;b.append(k);b.setAttribute('aria-current','true')}
    b.onclick=()=>lgPick(l);box.append(b)})
}
// the state of the «Язык» row; the status carries the code (the page redraws when it changes elsewhere)
function langRowText(s){
  const c=s&&s.lang;
  if(c&&c!==lgCur){lgCur=c;lgDraw()}
  return lgName(lgCur)
}
async function lgPick(l){
  buzz();
  if(l.code===lgCur)return;
  try{await api('/api/lang',{code:l.code});lgCur=l.code;lgDraw();if(window.setRows)setRows();toast('Язык: '+l.name)}
  catch(e){toast('Не получилось: '+tvErr(e))}
}
lgDraw();
</script>
"""
