"""The shared TV <-> phone onboarding sheet of the page: style, markup and script, as strings. The documents come
from mediastick_onboarding (status()["onboarding"]); this draws ONE universal sheet `#ob-sheet` from the one of any
flow (the device-code sign-in, the Google keys wizard, whatever comes next). No logic worth testing here;
inject() puts it at the end of the page, after the Accounts script, whose helpers it uses ($, buzz, copyText,
accSafe, accEl, ykOpen). Everything is prefixed `ob` / `ob-` so it cannot collide with the page's own names.
The page's status poll calls obNote(status.onboarding)."""

TAIL = r"""
<style>
.ob-sheet{position:fixed;inset:0;z-index:60;display:flex;align-items:flex-end;justify-content:center}
.ob-back{position:absolute;inset:0;background:rgba(0,0,0,.6)}
.ob-box{position:relative;width:100%;max-width:440px;max-height:92vh;overflow-y:auto;background:var(--card);border-radius:24px 24px 0 0;padding:16px 16px calc(16px + env(safe-area-inset-bottom));box-shadow:0 -8px 32px rgba(0,0,0,.45)}
.ob-hd{display:flex;align-items:center;gap:12px}
.ob-ico{flex:none;width:44px;height:44px;border-radius:12px;background:var(--card2);display:flex;align-items:center;justify-content:center;font-weight:700;font-size:20px}
.ob-ico.ob-youtube{background:#ff3d3d}
.ob-ico.ob-sweettv{background:#7b5cff}
.ob-tt{flex:1;min-width:0}
.ob-tt b{display:block;font-size:19px;font-weight:600;overflow-wrap:anywhere}
.ob-sub{color:var(--dim);font-size:14px;overflow-wrap:anywhere}
.ob-x{flex:none;background:none;border:0;color:var(--dim);font-size:15px;min-height:44px;padding:0 4px}
.ob-steps{list-style:none;margin:14px 0 0;padding:0}
.ob-steps li{display:flex;align-items:center;gap:12px;min-height:44px;color:var(--faint)}
.ob-steps li.now{color:#fff;font-weight:700}
.ob-steps li.done{color:var(--dim)}
.ob-dot{flex:none;width:26px;height:26px;border-radius:50%;border:2px solid var(--faint);display:flex;align-items:center;justify-content:center;font-size:13px}
.ob-steps li.now .ob-dot{border-color:#fff;border-width:3px}
.ob-steps li.done .ob-dot{border-color:var(--ok);background:var(--ok);color:var(--bg)}
.ob-dot svg{width:14px;height:14px;fill:none;stroke:currentColor;stroke-width:3;stroke-linecap:round;stroke-linejoin:round}
.ob-vh{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap}
.ob-warn{margin-top:12px;padding:10px 12px;border-radius:12px;background:rgba(255,107,107,.14);color:var(--bad);font-size:14px}
.ob-items{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.ob-item{padding:6px 12px;border-radius:999px;background:var(--bg);font-size:14px;color:var(--dim)}
.ob-item.ok{color:var(--ok)}
.ob-codebox{margin-top:14px;padding:12px;border-radius:16px;background:var(--bg);text-align:center}
.ob-codebox small{display:block;color:var(--dim);font-size:13px}
.ob-code{font:700 clamp(24px,8vw,34px)/1.2 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:.06em;margin:6px 0 8px;user-select:all;-webkit-user-select:all;overflow-wrap:anywhere}
.ob-hint{margin-top:12px;color:var(--dim);font-size:14px}
.ob-box .btn{margin-top:12px}
.ob-wait{display:flex;align-items:center;gap:10px;margin-top:14px;color:var(--dim);font-size:15px}
.ob-spin{flex:none;width:18px;height:18px;border-radius:50%;border:3px solid var(--card2);border-top-color:#fff;animation:obspin 1s linear infinite}
@keyframes obspin{to{transform:rotate(360deg)}}
@media (prefers-reduced-motion:reduce){.ob-spin{animation:none}}
.ob-fin{display:none;text-align:center;font-size:20px;font-weight:600;padding:28px 0}
.ob-sheet.ob-end .ob-live{display:none}
.ob-sheet.ob-end .ob-fin{display:block}
.ob-mini{display:none;width:calc(100% - 32px);max-width:408px;min-height:52px;align-items:center;justify-content:space-between;gap:10px;padding:0 18px;border:0;border-radius:16px;background:#fff;color:var(--bg);font-weight:600;box-shadow:0 6px 24px rgba(0,0,0,.4)}
.ob-sheet.ob-min{inset:auto 0 calc(76px + env(safe-area-inset-bottom)) 0;pointer-events:none}
.ob-sheet.ob-min .ob-back,.ob-sheet.ob-min .ob-box{display:none}
.ob-sheet.ob-min .ob-mini{display:flex;pointer-events:auto}
@media (min-width:900px){.ob-sheet{align-items:center}.ob-box{border-radius:24px}.ob-sheet.ob-min{inset:auto 0 16px 0}}
</style>
<div id="ob-sheet" class="ob-sheet hide" role="dialog" aria-labelledby="ob-ttl">
  <div class="ob-back" id="ob-back"></div>
  <div class="ob-box">
    <div class="ob-hd">
      <span id="ob-ico" class="ob-ico" aria-hidden="true"></span>
      <div class="ob-tt"><b id="ob-ttl"></b><div id="ob-sub" class="ob-sub" aria-live="polite"></div></div>
      <button id="ob-hide" class="ob-x" type="button">Скрыть</button>
    </div>
    <div class="ob-live">
      <ol id="ob-steps" class="ob-steps"></ol>
      <div id="ob-warn" class="ob-warn hide"></div>
      <div id="ob-items" class="ob-items hide"></div>
      <div id="ob-codebox" class="ob-codebox hide"><small>Код, если спросят</small><div id="ob-code" class="ob-code"></div><button id="ob-copy" class="btn sm wide" type="button">Скопировать</button></div>
      <div id="ob-hint" class="ob-hint hide"></div>
      <a id="ob-open" class="btn acc wide hide" target="_blank" rel="noopener"></a>
      <button id="ob-paste" class="btn acc wide hide" type="button"></button>
      <div id="ob-wait" class="ob-wait hide"><span class="ob-spin" aria-hidden="true"></span><span id="ob-waitt"></span></div>
    </div>
    <div id="ob-fin" class="ob-fin" role="status"></div>
  </div>
  <button id="ob-mini" class="ob-mini" type="button"><span id="ob-mt"></span><span>Показать</span></button>
</div>
<script>
// ---- onboarding: the TV's picture of a flow that needs this phone, drawn as one sheet ----
let obCur=null, obCurKey='', obSig='', obHid={}, obEnded={}, obCloseT=null;
const obStr=v=>typeof v==='string'?v:'';
const obPh=p=>p&&typeof p==='object'?(obStr(p.phone)||obStr(p.tv)):'';
const obSafe=u=>typeof accSafe==='function'?accSafe(u):'';   // every link goes through the sign-in pages' whitelist
const obKey=d=>d.service+'|'+d.flow+'|'+(d.step|0);
// this phone already shows that flow: the sign-in sheet of the service, or the key wizard
function obSuppressed(d){
  const a=$('acc-sheet');
  if(a&&!a.classList.contains('hide')&&typeof accSheet!=='undefined'&&accSheet&&accSheet.svc===d.service)return true;
  const y=$('acc-yk');
  return d.flow==='keys'&&!!y&&!y.classList.contains('hide')
}
function obShow(on){const s=$('ob-sheet');s.classList.toggle('hide',!on);if(!on)s.classList.remove('ob-min','ob-end')}
function obClose(){if(obCloseT)return;obCur=null;obSig='';obShow(false)}
function obPut(id,text){const e=$(id);e.textContent=text||'';e.classList.toggle('hide',!text)}
function obRender(d){
  const steps=Array.isArray(d.steps)?d.steps.slice(0,8):[], n=steps.length, cur=Math.max(0,d.step|0);
  const ico=$('ob-ico'), name=obStr(d.service).replace(/[^a-z0-9_-]/g,'');
  ico.className='ob-ico ob-'+name;ico.textContent=name.charAt(0).toUpperCase();
  const title=obPh(d.title)||'Нужна ваша помощь';
  $('ob-ttl').textContent=title;
  const kick=obPh(d.kicker)||(d.flow==='signin'?'ТВ попросил вход':'ТВ ждёт вас');
  const prog=n&&cur?'шаг '+cur+' из '+n:'';
  $('ob-sub').textContent=kick+(prog?' · '+prog:'');
  $('ob-mt').textContent=title+(prog?' · '+prog:'');
  const ol=$('ob-steps');ol.textContent='';
  steps.forEach((s,i)=>{
    const k=i+1<cur?'done':i+1===cur?'now':'todo';
    const li=accEl('li',k);if(k==='now')li.setAttribute('aria-current','step');
    const dot=accEl('span','ob-dot');
    if(k==='done'){dot.innerHTML='<svg viewBox="0 0 24 24"><path d="M5 12l5 5 9-10"/></svg>'}else dot.textContent=String(i+1);
    li.append(dot,accEl('span','',obPh(s)));
    if(k==='done')li.append(accEl('span','ob-vh',' — выполнено'));
    ol.append(li)});
  ol.classList.toggle('hide',!n);
  obPut('ob-warn',obPh(d.warn));obPut('ob-hint',obPh(d.hint));
  const items=Array.isArray(d.items)?d.items.slice(0,6):[], box=$('ob-items');box.textContent='';
  items.forEach(it=>{if(it&&obStr(it.label))box.append(accEl('span','ob-item'+(it.s==='ok'?' ok':''),(it.s==='ok'?'✓ ':'… ')+obStr(it.label)))});
  box.classList.toggle('hide',!box.childNodes.length);
  const code=obStr(d.code);$('ob-code').textContent=code;$('ob-codebox').classList.toggle('hide',!code);
  const act=d.action&&typeof d.action==='object'?d.action:null, kind=act?act.kind:(d.link?'link':''), lbl=act?obStr(act.label):'';
  const url=kind==='link'?obSafe((act&&act.url)||d.link):'', o=$('ob-open');
  o.classList.toggle('hide',!url);if(url){o.href=url;o.textContent=lbl||'Открыть страницу'}
  const pb=$('ob-paste'), keys=kind==='paste'&&d.flow==='keys'&&typeof ykOpen==='function';
  pb.classList.toggle('hide',!keys);if(keys)pb.textContent=lbl||'Продолжить';
  const w=kind==='wait'&&lbl;$('ob-wait').classList.toggle('hide',!w);$('ob-waitt').textContent=w?lbl:''
}
function obEnd(d){
  if(obEnded[d.service]===d.updated)return;obEnded[d.service]=d.updated;
  $('ob-fin').textContent=d.state==='done'?'Готово':d.state==='cancelled'?'Отменено':'Не получилось';
  obShow(true);$('ob-sheet').classList.add('ob-end');obCur=null;obSig='';
  clearTimeout(obCloseT);obCloseT=setTimeout(()=>{obCloseT=null;obShow(false)},2600);
  if(d.state==='done')buzz()
}
// called with the status the page polls anyway: the documents of the flows that wait for this phone
function obNote(list){
  const docs=(Array.isArray(list)?list:[]).filter(d=>d&&typeof d==='object'&&typeof d.service==='string'&&/^[a-z0-9_-]+$/.test(d.service));
  const live={};docs.forEach(d=>{live[d.service]=1});
  Object.keys(obHid).forEach(k=>{if(!live[k])delete obHid[k]});
  Object.keys(obEnded).forEach(k=>{if(!live[k])delete obEnded[k]});
  const ended=docs.find(d=>d.state&&d.state!=='active'&&obEnded[d.service]!==d.updated);
  if(ended){obEnd(ended);return}
  const act=docs.filter(d=>(!d.state||d.state==='active')&&!obSuppressed(d));
  const d=act.find(x=>obCur&&x.service===obCur)||act[0];
  if(!d){obClose();return}
  if(obCloseT){clearTimeout(obCloseT);obCloseT=null}
  const fresh=obCur!==d.service, sig=JSON.stringify([d.flow,d.kicker,d.title,d.step,d.steps,d.code,d.link,d.action,d.hint,d.warn,d.items]);
  if(obHid[d.service]&&obHid[d.service]!==obKey(d))delete obHid[d.service];   // moved on to its next step: it comes back
  const hid=!!obHid[d.service], s=$('ob-sheet'), wasMin=s.classList.contains('ob-min');
  obCur=d.service;obCurKey=obKey(d);
  if(sig!==obSig||fresh){obSig=sig;obRender(d)}
  s.classList.remove('hide','ob-end');s.classList.toggle('ob-min',hid);
  if(!hid&&(fresh||wasMin))buzz()
}
function obMin(){if(!obCur)return;obHid[obCur]=obCurKey;$('ob-sheet').classList.add('ob-min')}
$('ob-hide').onclick=obMin;
$('ob-back').onclick=obMin;
$('ob-mini').onclick=()=>{if(obCur)delete obHid[obCur];$('ob-sheet').classList.remove('ob-min')};
$('ob-paste').onclick=()=>{buzz();obMin();ykOpen(true)};
$('ob-copy').onclick=()=>{
  const b=$('ob-copy'),el=$('ob-code');buzz();
  copyText(el.textContent).then(ok=>{
    if(!ok){const r=document.createRange();r.selectNodeContents(el);const s=getSelection();s.removeAllRanges();s.addRange(r)}
    b.textContent=ok?'Скопировано':'Выделено — скопируйте вручную';setTimeout(()=>b.textContent='Скопировать',2000)})
};
</script>
"""


def inject(page):
    """The page with the onboarding sheet put before its closing tag (after the Accounts script it builds on);
    a page without one is left as it is."""
    return page.replace("</body>", TAIL + "</body>", 1)
