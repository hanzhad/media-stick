"""The "Google key for YouTube" wizard's sheet: style, markup and script, as strings. It is part of the
Accounts page (it uses accEl, accCall, accSafe, accStart from panel_accounts_ui.py and the page's own $, buzz,
armed, copyText); panel_accounts.inject() appends it after the Accounts script. Everything is prefixed `acc-` / `yk`.
The steps' text and links (also the Android intent and the Safari form of each), the checklist and what a key, a
client ID and a secret look like come from panel_ytkeys.WIZARD, one description for the page and the tests.
The step the owner is on lives on the panel (the TV reads it from there); the phone keeps only an "unfinished" flag
in localStorage. The three values live in script variables until they are saved or the page goes: they are sent to
the panel in a POST body (to be checked, then saved) and nowhere else."""
import json

TAIL = r"""
<style>
.acc-ykb{background:var(--bg)}
.acc-yk-p{margin:8px 0;color:var(--dim);font-size:15px}
.acc-yk-big{font-size:20px;font-weight:600;padding:14px 0 6px}
.acc-yk-row{display:flex;gap:8px}
.acc-yk-row .btn{flex:1 1 0;min-width:0;padding:0 8px}
.acc-yk-st{margin:10px 0 0;border:1px solid transparent;border-radius:18px;background:var(--card)}
.acc-yk-st.cur{background:#1f2433;border-color:#3a4258}
.acc-yk-st.pend{opacity:.55}
.acc-yk-sh{display:flex;align-items:center;gap:12px;width:100%;min-height:52px;padding:6px 14px;background:none;border:0;color:inherit;font-size:17px;font-weight:600;text-align:left;touch-action:manipulation}
.acc-yk-n{flex:0 0 28px;height:28px;border-radius:50%;display:flex;align-items:center;justify-content:center;background:#2a3040;font-size:14px}
.acc-yk-st.done .acc-yk-n{background:#2f6b4c}
.acc-yk-sb{padding:0 14px 14px}
.acc-yk-a{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.acc-yk-a .btn{flex:1 1 140px;margin-top:0;padding:0 8px}
.acc-yk-st .btn{border-radius:999px;min-height:48px}
.acc-yk-st .btn.acc{background:#f2f3f5;color:var(--bg)}
.acc-yk-h{margin-top:8px;color:var(--faint);font-size:13px}
.acc-yk-cv{display:flex;flex-wrap:wrap;align-items:center;gap:6px 8px;margin-top:10px}
.acc-yk-cv .acc-yk-h{flex:1 1 100%;margin:0}
.acc-yk-cv .acc-yk-url{flex:1 1 160px}
.acc-yk-cv .btn{flex:0 0 auto;margin-top:0}
.acc-yk-url{flex:1 1 100%;padding:10px 12px;background:var(--bg);border-radius:12px;color:var(--dim);font-size:13px;user-select:all;-webkit-user-select:all;overflow-wrap:anywhere}
.acc-yk-m{margin-top:10px;color:var(--dim);font-size:14px;min-height:1.4em}
.acc-yk-m.bad{color:var(--bad)}
.acc-yk-warn{margin:10px 0 0;padding:10px 12px;border-radius:12px;background:rgba(240,198,116,.12);color:#f0c674;font-size:14px}
.acc-yk-tk{display:flex;align-items:center;gap:12px;min-height:44px;margin:0;color:inherit;font-size:15px}
.acc-yk-tk input{width:28px;min-height:28px;flex:0 0 auto;accent-color:#2f6b4c}
.acc-yk-slot{display:flex;flex-wrap:wrap;align-items:center;gap:4px 10px;margin-top:8px;padding:10px 12px;min-height:44px;border-radius:12px;background:var(--bg);font-size:14px;color:var(--dim)}
.acc-yk-slot b{flex:1 1 100%;font-size:13px;font-weight:600;color:var(--faint)}
.acc-yk-slot span{flex:1 1 0;min-width:0;overflow-wrap:anywhere}
.acc-yk-slot.ok span{color:#7bd3a4}
.acc-yk-slot.bad span{color:var(--bad)}
.acc-yk-slot .btn{flex:0 0 auto;min-height:44px;padding:0 14px}
.acc-yk-up{margin-top:12px;color:var(--dim);font-size:14px}
.acc-yk-up input{min-height:44px;padding-top:10px}
.acc-yk-ln{display:flex;gap:8px;margin-top:8px}
.acc-yk-ln input{flex:1;min-width:0}
.acc-yk-ln .btn{flex:0 0 auto}
.acc-yk-note{margin-top:14px;color:var(--faint);font-size:13px}
.acc-yk-note a{color:inherit}
#acc-yk-cont{margin:0 0 14px}
</style>
<div id="acc-yk" class="sheet acc-sheet hide" role="dialog" aria-label="Ключ Google для YouTube">
  <div class="sheet-back acc-back" id="acc-yk-back"></div>
  <div class="sheet-box acc-box acc-ykb">
    <div class="acc-hd"><b>Ключ Google для YouTube</b><button id="acc-yk-x" class="acc-x" aria-label="Закрыть мастер ключей">Закрыть</button></div>
    <div id="acc-yk-body"></div>
  </div>
</div>
<script>
// ---- the YouTube key wizard: four steps; the three values live in these variables only ----
const YK=@@WIZARD@@;
let ykStep=1, ykView='', ykMsg='', ykBad=false, ykSt=null, ykBusy=false, ykHidden=false, ykTicks=[], ykFallback=false;
// which phone this is, to open the links the way that gets out of the panel; the tests cannot run this, a person must
const ykUA=navigator.userAgent||'';
const ykIOS=/iPhone|iPad|iPod/.test(ykUA)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
const ykAndroid=/Android/i.test(ykUA);
const ykStandalone=navigator.standalone===true||!!(window.matchMedia&&matchMedia('(display-mode: standalone)').matches);
// what was found in the pasted text and what the panel (and Google) said of it: {s:'busy'|'ok'|'bad'|'net', msg, quota}
const ykVal={api_key:'',client_id:'',client_secret:''}, ykInfo={api_key:null,client_id:null,client_secret:null};
const ykRx={};Object.keys(YK.patterns).forEach(k=>{ykRx[k]=new RegExp(YK.patterns[k])});
const ykIdle={api_key:'ждём · начинается с AIza',client_id:'ждём · заканчивается на .apps.googleusercontent.com',client_secret:'ждём · начинается с GOCSPX-'};
const ykPaste=accEl('input');   // the spare place to paste into when the clipboard cannot be read
ykPaste.type='text';ykPaste.autocomplete='off';ykPaste.spellcheck=false;ykPaste.placeholder='Вставьте сюда';
ykPaste.setAttribute('autocapitalize','off');ykPaste.setAttribute('autocorrect','off');ykPaste.setAttribute('enterkeyhint','done');
ykPaste.setAttribute('aria-label','Поле для вставки ключа, ID или secret');
// what is kept on the phone: "not finished" (1); the step itself is the panel's, nothing the owner typed
const ykPending=()=>{try{return localStorage.getItem('acc-yk-open')==='1'}catch(e){return false}};
function ykKeep(){try{localStorage.setItem('acc-yk-open','1')}catch(e){}}
function ykDrop(){try{localStorage.removeItem('acc-yk-open')}catch(e){}}
const ykHas=()=>Object.keys(ykVal).some(k=>ykVal[k]);
function ykWipe(){Object.keys(ykVal).forEach(k=>{ykVal[k]='';ykInfo[k]=null});ykPaste.value=''}
// the TV shows the step: 1..N, or 0 when the wizard is closed; a failure here matters to nobody
function ykTell(n){accCall('ytkeys',{action:'step',step:n}).catch(()=>{})}
function ykGo(n){ykStep=n;ykKeep();ykTell(n);ykShow('step')}
function ykShow(v){ykView=v;ykDraw()}
function ykSay(t,bad){ykMsg=t||'';ykBad=!!bad;const m=$('acc-yk-body').querySelector('.acc-yk-m');if(m){m.textContent=ykMsg;m.classList.toggle('bad',ykBad)}}
function ykBtn(text,cls,fn,id){const b=accEl('button','btn '+cls,text);b.type='button';if(id)b.id=id;b.onclick=()=>{buzz();fn()};return b}
// Android: an intent link hands the page to the browser; anywhere else the link's own target=_blank opens a new tab
function ykOut(e,intent){
  if(!ykAndroid||!intent)return;
  try{location.href=intent;e.preventDefault()}catch(x){}
}
function ykLink(s,text,cls){
  const u=accSafe(s.url);if(!u)return null;
  const a=accEl('a',cls,text);a.href=u;a.target='_blank';a.rel='noopener';
  const intent=s.intent&&s.intent.indexOf('intent://'+u.slice(8)+'#Intent;')===0?s.intent:'';
  a.onclick=e=>ykOut(e,intent);return a
}
function ykSafari(s){
  const u=accSafe(s.url);if(!u||s.safari!=='x-safari-'+u)return null;
  const a=accEl('a','btn sm',YK.texts.safari);a.href=s.safari;return a
}
function ykCopy(s){
  const u=accSafe(s.url);if(!u)return null;
  const b=ykBtn(YK.texts.copy,'sm',()=>copyText(u).then(ok=>{
    if(ok){b.textContent=YK.texts.copied;setTimeout(()=>{b.textContent=YK.texts.copy},2000);return}
    if(!b.parentNode)return;
    let d=b.parentNode.querySelector('.acc-yk-url');   // no clipboard: show the link, selected, to copy by hand
    if(!d){d=accEl('div','acc-yk-url',u);b.parentNode.append(d)}
    const r=document.createRange();r.selectNodeContents(d);const g=getSelection();g.removeAllRanges();g.addRange(r);
    b.textContent='Скопируйте ссылку вручную'
  }));
  return b
}
// a value to paste on a Google page (our pages' links, the domain): its label, the value, a copy button
function ykCopyVal(label,value){
  const row=accEl('div','acc-yk-cv'),v=accEl('div','acc-yk-url',value);
  const b=ykBtn('Скопировать','sm',()=>copyText(value).then(ok=>{
    if(ok){b.textContent='Скопировано';setTimeout(()=>{b.textContent='Скопировать'},2000);return}
    const r=document.createRange();r.selectNodeContents(v);const g=getSelection();g.removeAllRanges();g.addRange(r);
    b.textContent='Скопируйте вручную'
  }));
  b.setAttribute('aria-label','Скопировать: '+label);
  row.append(accEl('div','acc-yk-h',label),v,b);
  return row
}
// a step's link: the button, "copy link" (and "open in Safari" on an iPhone), and what to expect
function ykLinks(s){
  const a=ykLink(s,s.button,'btn acc wide');if(!a)return [];
  a.setAttribute('aria-label',s.button+': '+s.title);
  const row=accEl('div','acc-yk-a'),c=ykCopy(s),sf=ykIOS?ykSafari(s):null;
  if(c)row.append(c);if(sf)row.append(sf);
  const out=[a,row,accEl('div','acc-yk-h',ykIOS&&ykStandalone?YK.texts.back:YK.texts.open)];
  if(ykStandalone&&!ykIOS)out.push(accEl('div','acc-yk-h',YK.texts.standalone));
  return out
}
function ykMsgEl(){const m=accEl('div','acc-yk-m'+(ykBad?' bad':''),ykMsg);m.setAttribute('aria-live','polite');return m}
function ykFoot(b){
  const n=accEl('div','acc-yk-note',YK.note+' ');const d=ykLink(YK.doc,YK.doc.button,'');
  if(d)n.append(d);
  b.append(n)
}
function ykDraw(){
  const b=$('acc-yk-body');b.textContent='';
  if(ykView==='load')b.append(accEl('div','acc-yk-p','Смотрю, что уже сохранено…'));
  else if(ykView==='set')ykSet(b);
  else ykSteps(b);
  if(ykView!=='load')ykFoot(b)
}
// ---- the four steps: finished ones fold to a check row, the next ones wait dimmed, any can be opened again ----
function ykSteps(b){
  b.append(accEl('p','acc-yk-p',YK.texts.intro.replace('%s',location.host)));
  YK.steps.forEach((s,i)=>{
    const n=i+1, cls=n<ykStep?'done':n===ykStep?'cur':'pend';
    const box=accEl('div','acc-yk-st '+cls), h=accEl('button','acc-yk-sh');
    h.type='button';h.setAttribute('aria-expanded',n===ykStep?'true':'false');
    h.setAttribute('aria-label','Шаг '+n+' из '+YK.steps.length+': '+s.title+(cls==='done'?', сделан':cls==='cur'?', текущий':', ещё нет'));
    h.append(accEl('span','acc-yk-n',cls==='done'?'✓':String(n)),accEl('span','',s.title));
    if(n!==ykStep)h.onclick=()=>{buzz();ykGo(n)};
    box.append(h);
    if(n===ykStep){const body=accEl('div','acc-yk-sb');ykStepBody(body,s,n);box.append(body)}
    b.append(box)
  })
}
function ykStepBody(b,s,n){
  if(ykIOS&&ykStandalone)b.append(accEl('p','acc-yk-p',YK.texts.ios_standalone));
  s.lines.forEach(t=>b.append(accEl('p','acc-yk-p',t)));
  if(s.ticks)ykChecklist(b,s);
  (s.copies||[]).forEach(c=>b.append(ykCopyVal(c.label,c.value)));
  b.append(...ykLinks(s));
  if(s.paste)ykPasteBox(b,n);
  if(n<YK.steps.length)b.append(ykBtn('Сделано, дальше','wide',()=>ykGo(n+1),'acc-yk-next'));
  b.append(ykMsgEl())
}
function ykChecklist(b,s){
  YK.ticks.forEach(t=>{
    const l=accEl('label','acc-yk-tk'),c=accEl('input');c.type='checkbox';c.checked=ykTicks.indexOf(t.id)>=0;
    c.onchange=()=>{
      buzz();const on=c.checked;ykTicks=ykTicks.filter(x=>x!==t.id);if(on)ykTicks.push(t.id);
      accCall('ytkeys',{action:'tick',id:t.id,on}).catch(()=>{})
    };
    l.append(c,accEl('span','',t.label));b.append(l)
  });
  if(s.warn)b.append(accEl('div','acc-yk-warn',s.warn))
}
// ---- the paste box: one button, the page works out whether it was a key, a client ID or a secret ----
const ykDetect=t=>{
  t=typeof t==='string'?t:'';if(t.length>YK.paste_max*2)return null;t=t.trim();if(!t||t.length>YK.paste_max)return null;
  const k=Object.keys(ykRx).find(x=>ykRx[x].test(t));return k?[k,t]:null
};
function ykShown(k){
  const i=ykInfo[k], v=ykVal[k];
  if(!i)return ['',ykIdle[k]];
  if(i.s==='busy')return ['','проверяю…'];
  if(i.s!=='ok')return ['bad',i.msg];
  if(k==='api_key')return ['ok','AIza…'+v.slice(-4)+' · '+(i.quota?'лимит на сегодня исчерпан, ключ верный':'работает')];
  if(k==='client_id')return ['ok',v.slice(0,4)+'…apps.googleusercontent.com · клиент для ТВ'];
  return ['ok','GOCSPX-… · принят']
}
function ykSlot(f){
  const [cls,text]=ykShown(f.name), i=ykInfo[f.name];
  const d=accEl('div','acc-yk-slot '+cls);d.append(accEl('b','',f.label),accEl('span','',text));
  d.setAttribute('aria-label',f.label+': '+text);
  if(i&&i.s==='net'&&ykVal[f.name])d.append(ykBtn('Проверить снова','sm',()=>ykTake(ykVal[f.name])));
  return d
}
function ykPasteBox(b,n){
  YK.fields.forEach(f=>b.append(ykSlot(f)));
  b.append(ykBtn('Вставить из буфера','acc wide',ykFromClipboard,'acc-yk-paste'));
  if(ykFallback||!(navigator.clipboard&&navigator.clipboard.readText)){
    const ln=accEl('div','acc-yk-ln');
    ln.append(ykPaste,ykBtn('Добавить','',()=>{const t=ykPaste.value;ykPaste.value='';ykTake(t)}));
    b.append(ln)
  }
  if(n===YK.steps.length){
    const up=accEl('label','acc-yk-up','Или загрузить скачанный JSON клиента'),f=accEl('input');
    f.type='file';f.accept='application/json,.json';f.setAttribute('aria-label','Файл JSON клиента');
    f.onchange=()=>{const x=f.files&&f.files[0];f.value='';if(x)ykFromJson(x)};
    up.append(f);b.append(up);
    const all=Object.keys(ykInfo).every(k=>ykInfo[k]&&ykInfo[k].s==='ok');
    const any=Object.keys(ykInfo).some(k=>ykInfo[k]&&ykInfo[k].s==='net');
    const go=ykBtn('Сохранить и войти','acc wide',()=>ykSave(false),'acc-yk-save');go.disabled=!all;b.append(go);
    if(any&&Object.keys(ykVal).every(k=>ykVal[k]&&ykInfo[k]&&ykInfo[k].s!=='bad'&&ykInfo[k].s!=='busy'))
      b.append(ykBtn('Сохранить без проверки','wide',()=>ykSave(true)))
  }
}
async function ykFromClipboard(){
  if(!(navigator.clipboard&&navigator.clipboard.readText)){ykFallback=true;ykDraw();return}
  try{await ykTake(await navigator.clipboard.readText())}
  catch(e){ykFallback=true;ykDraw();ykSay('Браузер не дал прочитать буфер. Вставьте в поле и нажмите «Добавить».',true)}
}
// one pasted text: what it is, then the panel's check (a key and a client ID are asked of Google there)
async function ykTake(text){
  const d=ykDetect(text);
  if(!d){ykSay(YK.texts.unknown,true);return false}
  const k=d[0], v=d[1];
  ykVal[k]=v;ykInfo[k]={s:'busy'};ykSay('');ykDraw();
  try{
    const j=await accCall('ytkeys',{action:'verify',value:v});
    ykInfo[k]=j.works?{s:'ok',quota:j.check==='quota'}:j.check==='net'?{s:'net',msg:j.message}:{s:'bad',msg:j.message};
    if(ykInfo[k].s==='bad')ykVal[k]=''
  }catch(e){ykInfo[k]={s:'net',msg:e.message}}
  ykDraw();return true
}
// the client JSON Google lets one download: {"installed":{client_id,client_secret}} or {"web":{...}}; it is read here, never uploaded
async function ykFromJson(file){
  if(file.size>YK.json_max){ykSay('Файл слишком большой для JSON клиента.',true);ykDraw();return}
  let o=null;
  try{const j=JSON.parse(await file.text());o=j&&(j.installed||j.web)}catch(e){}
  if(!o||typeof o.client_id!=='string'||typeof o.client_secret!=='string'){ykSay('Не похоже на JSON клиента Google.',true);ykDraw();return}
  const a=await ykTake(o.client_id), b=await ykTake(o.client_secret);
  if(a&&b)ykSay('')
}
function ykSet(b){
  const full=ykSt&&ykSt.set;
  b.append(accEl('div','acc-yk-big',full?'Ключи заданы (…'+ykSt.last4+')':'Заданы не все три значения'));
  b.append(accEl('p','acc-yk-p',full?'Сами значения здесь не показываются.':'Нажмите «Заменить» и введите их заново или «Удалить».'));
  const row=accEl('div','acc-yk-row');
  if(full)row.append(ykBtn('Проверить','',ykCheck));
  row.append(ykBtn('Заменить','',()=>{ykSay('');ykGo(1)}));
  row.append(ykBtn('Удалить','',()=>{if(armed('acc-yk-del','Нажмите ещё раз, чтобы удалить'))ykClear()},'acc-yk-del'));
  b.append(row,ykMsgEl());
  if(full)b.append(ykBtn('Войти в YouTube заново','acc wide',ykSignin))
}
function ykSignin(){ykClose();accStart('youtube')}
// "Закрыть" ends the wizard (the panel keeps the step for the next «Ключи»); a tap beside the sheet only puts it aside
function ykClose(){ykHidden=false;ykDrop();ykTell(0);ykHide()}
function ykAside(){ykHidden=true;ykHide()}
function ykHide(){$('acc-yk').classList.add('hide');ykBanner()}
// on the Accounts tab: an unfinished wizard that is not on screen can be taken up again
function ykBanner(){
  const b=$('acc-yk-cont');if(!b)return;
  const show=ykPending()&&$('acc-yk').classList.contains('hide');
  b.classList.toggle('hide',!show);
  if(show)b.textContent=YK.texts.resume.replace('%d',ykStep).replace('%d',YK.steps.length)
}
async function ykCall(body,doing){
  if(ykBusy)return null;ykBusy=true;ykSay(doing);
  try{return await accCall('ytkeys',body)}
  catch(e){ykSay(e.message,true);return null}
  finally{ykBusy=false}
}
// «Сохранить и войти»: the panel checks the key again, hands the three values to Kodi, and sign-in starts as from the card
async function ykSave(skip){
  const body={action:'save'};Object.keys(ykVal).forEach(k=>{body[k]=ykVal[k]});
  if(skip)body.skip_check=true;
  const j=await ykCall(body,'Проверяю и записываю… это может занять до 20 секунд.');
  if(!j)return;
  ykWipe();ykSt={set:true,last4:j.last4||''};
  ykDrop();   // finished: nothing to come back to (the panel has already cleared the TV's step)
  ykSay('');ykHide();buzz();accStart('youtube')
}
async function ykCheck(){
  const j=await ykCall({action:'check'},'Проверяю ключ…');
  if(j)ykSay(j.message,!j.works)
}
async function ykClear(){
  const j=await ykCall({action:'clear'},'Удаляю…');
  if(!j)return;
  ykSt={set:false,last4:''};ykGo(1);ykSay('Ключи удалены.')
}
// `resume`: the wizard comes back by itself (the page was reloaded, or the phone returned from the browser) or
// from the banner, so it goes to the panel's step even when some of the keys are already there
async function ykOpen(resume){
  if(!resume)buzz();
  ykHidden=false;$('acc-yk').classList.remove('hide');ykBanner();ykSay('');ykShow('load');
  try{
    const j=await accCall('ytkeys',{action:'status'});ykSt=j;
    if(resume&&j.set){ykDrop();ykTell(0);ykHide();return}   // saved in the meantime (from another phone)
    const r=await accCall('ytkeys',{action:'resume',fresh:!ykHas()});
    ykTicks=Array.isArray(r.ticks)?r.ticks:[];ykStep=Math.max(1,Math.min(YK.steps.length,r.step|0||1));
    if(!resume&&(j.set||j.partial))ykShow('set');
    else ykGo(ykStep)
  }catch(e){ykSay(e.message,true);ykGo(ykStep)}
}
// the page loaded, or came back to the front (visibilitychange, pageshow): the unfinished wizard is on its step again
function ykResume(){
  if(document.hidden)return;
  if(!$('acc-yk').classList.contains('hide')){if(ykView==='step')ykTell(ykStep);return}   // already there: tell the TV it is alive
  if(ykPending()&&!ykHidden)ykOpen(true);else ykBanner()
}
$('acc-yk-x').onclick=ykClose;
$('acc-yk-back').onclick=ykAside;
if($('acc-yk-cont'))$('acc-yk-cont').onclick=()=>{buzz();ykOpen(true)};
document.addEventListener('visibilitychange',ykResume);
addEventListener('pageshow',ykResume);
ykResume();
</script>
"""


def tail(wizard):
    """The style, the sheet and the script; the script gets the steps' description as JSON."""
    return TAIL.replace("@@WIZARD@@", json.dumps(wizard, ensure_ascii=False))
