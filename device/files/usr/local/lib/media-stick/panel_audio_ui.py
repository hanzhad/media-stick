"""The «Звук» part of the page: settings row, output selector section, style, and script."""

ROW = """<button class="srow" data-sp="audio"><svg class="i"><use href="#i-vup"/></svg><span class="sname">Звук</span><span class="sval" id="sv-audio"></span><span class="chev" aria-hidden="true">›</span></button>
      """

SECTION = """<section id="t-audio" data-tab="settings" data-spage="audio" class="hide">
    <h2 class="au-title">Звук</h2>
    <div id="au-list" class="au-rows">
      <button type="button" class="au-row" data-out="hdmi"><span class="au-tx"><b>HDMI (телевизор)</b><small>Звук через телевизор по умолчанию</small></span><span class="au-ck" hidden></span></button>
      <button type="button" class="au-row" data-out="headphones"><span class="au-tx"><b>3.5 мм (наушники / колонки)</b><small>Аналоговый выход приставки</small></span><span class="au-ck" hidden></span></button>
    </div>
    <p class="au-note">Выбор сохраняется и применяется на приставке сразу.</p>
  </section>"""

TAIL = r"""
<style>
.au-title{margin:0 6px 14px;font-size:24px;font-weight:600;letter-spacing:0;text-transform:none;color:inherit}
.au-rows{background:var(--card);border-radius:20px;overflow:hidden;margin:0 0 14px}
.au-row{display:flex;align-items:center;gap:12px;width:100%;min-height:56px;padding:10px 16px;background:none;border:0;border-top:1px solid var(--line);color:inherit;font:inherit;font-size:17px;text-align:left;touch-action:manipulation}
.au-row:first-child{border-top:0}
.au-row:active{background:var(--card2)}
.au-tx{flex:1 1 0;min-width:0}
.au-tx b{display:block;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.au-tx small{display:block;margin-top:1px;color:var(--dim);font-size:14px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.au-ck{flex:none;display:flex;color:var(--ok)}
.au-note{margin:8px 6px 0;color:var(--faint);font-size:13px;line-height:1.4}
@media (min-width:900px){#t-audio{grid-area:audio;max-width:480px}}
</style>
<script>
const AU_TICK='<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
const AU_LABELS={hdmi:'HDMI',headphones:'3.5 мм'};
let auCur='hdmi';
function auDraw(){
  document.querySelectorAll('#au-list .au-row').forEach(b=>{
    const on=b.dataset.out===auCur;
    const ck=b.querySelector('.au-ck');
    if(ck){ck.innerHTML=on?AU_TICK:'';ck.hidden=!on}
    if(on)b.setAttribute('aria-current','true');else b.removeAttribute('aria-current');
  });
}
function audioRowText(s){
  const v=s&&s.audio_out;
  if(v==='hdmi'||v==='headphones'){if(v!==auCur){auCur=v;auDraw()}}
  return AU_LABELS[auCur]||'HDMI';
}
async function auPick(out){
  buzz();
  if(out===auCur)return;
  try{
    await api('/api/audio',{output:out});
    auCur=out;auDraw();
    if(lastStatus)lastStatus.audio_out=out;
    if(window.setRows)setRows();
    toast('Звук: '+(AU_LABELS[out]||out));
  }catch(e){toast('Не получилось: '+tvErr(e))}
}
document.querySelectorAll('#au-list .au-row').forEach(b=>{b.onclick=()=>auPick(b.dataset.out)});
auDraw();
</script>
"""
