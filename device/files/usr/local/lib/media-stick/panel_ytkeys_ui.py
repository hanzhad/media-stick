"""The "Google keys for YouTube" wizard's sheet: style, markup and script, as strings. It is part of the
Accounts page (it uses accEl, accCall, accSafe, accStart from panel_accounts_ui.py and the page's own $, buzz,
armed, copyText); panel_accounts.inject() appends it after the Accounts script. Everything is prefixed `acc-` / `yk`.
The steps' text and links (also the Android intent and the Safari form of each) come from panel_ytkeys.WIZARD, one
description for the page and the tests. The wizard remembers only its step number and an "unfinished" flag in
localStorage and tells the panel (and through it the TV) its step; no value from a field goes to either."""
import json

TAIL = r"""
<style>
.acc-ykb{max-height:92vh;overflow-y:auto;overscroll-behavior:contain}
.acc-yk-t{font-size:18px;font-weight:600;margin:6px 0 4px}
.acc-yk-p{margin:8px 0;color:var(--dim);font-size:15px}
.acc-yk-ok{display:flex;align-items:center;gap:12px;margin:14px 0 0;min-height:52px;font-size:17px;color:inherit}
.acc-yk-ok input{width:28px;min-height:28px;flex:0 0 auto;accent-color:#fff}
.acc-yk-big{font-size:20px;font-weight:600;padding:14px 0 6px}
.acc-yk-row{display:flex;gap:8px}
.acc-yk-row .btn{flex:1 1 0;min-width:0;padding:0 8px}
.acc-yk-a{display:flex;flex-wrap:wrap;gap:8px;margin-top:8px}
.acc-yk-a .btn{flex:1 1 140px;margin-top:0;padding:0 8px}
.acc-yk-h{margin-top:8px;color:var(--faint);font-size:13px}
.acc-yk-url{flex:1 1 100%;padding:10px 12px;background:var(--bg);border-radius:12px;color:var(--dim);font-size:13px;user-select:all;-webkit-user-select:all;overflow-wrap:anywhere}
.acc-yk-m{margin-top:10px;color:var(--dim);font-size:14px;min-height:1.4em}
.acc-yk-m.bad{color:var(--bad)}
.acc-yk-note{margin-top:14px;color:var(--faint);font-size:13px}
.acc-yk-note a{color:inherit}
#acc-yk-cont{margin:0 0 14px}
</style>
<div id="acc-yk" class="acc-sheet hide" role="dialog" aria-label="Ключи Google для YouTube">
  <div class="acc-back" id="acc-yk-back"></div>
  <div class="acc-box acc-ykb">
    <div class="acc-hd"><b>Ключи Google для YouTube</b><button id="acc-yk-x" class="acc-x">Закрыть</button></div>
    <div id="acc-yk-body"></div>
  </div>
</div>
<script>
// ---- the YouTube keys wizard: steps with links, then three fields; the values live in these inputs only ----
const YK=@@WIZARD@@;
let ykStep=1, ykView='', ykMsg='', ykBad=false, ykSt=null, ykBusy=false, ykSkip=false, ykLast4='', ykNote='', ykHidden=false;
// which phone this is, to open the links the way that gets out of the panel; the tests cannot run this, a person must
const ykUA=navigator.userAgent||'';
const ykIOS=/iPhone|iPad|iPod/.test(ykUA)||(navigator.platform==='MacIntel'&&navigator.maxTouchPoints>1);
const ykAndroid=/Android/i.test(ykUA);
const ykStandalone=navigator.standalone===true||!!(window.matchMedia&&matchMedia('(display-mode: standalone)').matches);
const ykIn={};
YK.fields.forEach(f=>{
  const i=accEl('input');i.type=f.secret?'password':'text';i.autocomplete='off';i.spellcheck=false;
  i.setAttribute('autocapitalize','off');i.setAttribute('autocorrect','off');i.setAttribute('enterkeyhint','done');
  i.placeholder=f.label;ykIn[f.name]=i
});
// what is kept on the phone: the step number and "not finished" (1); nothing the owner typed
const ykSaved=()=>{try{return Math.max(1,Math.min(YK.steps.length+1,parseInt(localStorage.getItem('acc-yk-step'),10)||1))}catch(e){return 1}};
const ykPending=()=>{try{return localStorage.getItem('acc-yk-open')==='1'}catch(e){return false}};
function ykKeep(n){try{localStorage.setItem('acc-yk-step',String(n));localStorage.setItem('acc-yk-open','1')}catch(e){}}
function ykDrop(forgetStep){try{localStorage.removeItem('acc-yk-open');if(forgetStep)localStorage.removeItem('acc-yk-step')}catch(e){}}
// the TV shows the step: 1..N, or 0 when the wizard is closed or finished; a failure here matters to nobody
function ykTell(n){accCall('ytkeys',{action:'step',step:n}).catch(()=>{})}
function ykGo(n){ykStep=n;ykKeep(n);ykTell(n);ykShow('step')}
function ykShow(v){ykView=v;ykDraw()}
function ykSay(t,bad){ykMsg=t||'';ykBad=!!bad;const m=$('acc-yk-body').querySelector('.acc-yk-m');if(m){m.textContent=ykMsg;m.classList.toggle('bad',ykBad)}}
function ykBtn(text,cls,fn,id){const b=accEl('button','btn '+cls,text);if(id)b.id=id;b.onclick=()=>{buzz();fn()};return b}
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
// a step's link: the button, "copy link" (and "open in Safari" on an iPhone), and what to expect
function ykLinks(s){
  const a=ykLink(s,s.button,'btn acc wide');if(!a)return [];
  const row=accEl('div','acc-yk-a'),c=ykCopy(s),sf=ykIOS?ykSafari(s):null;
  if(c)row.append(c);if(sf)row.append(sf);
  const out=[a,row,accEl('div','acc-yk-h',ykIOS&&ykStandalone?YK.texts.back:YK.texts.open)];
  if(ykStandalone&&!ykIOS)out.push(accEl('div','acc-yk-h',YK.texts.standalone));
  return out
}
function ykField(name){const f=YK.fields.find(x=>x.name===name);const l=accEl('label','',f.label);return [l,ykIn[name]]}
function ykMsgEl(){const m=accEl('div','acc-yk-m'+(ykBad?' bad':''),ykMsg);return m}
function ykFoot(b){
  const n=accEl('div','acc-yk-note',YK.note+' ');const d=ykLink(YK.doc,YK.doc.button,'');
  if(d)n.append(d);
  b.append(n)
}
function ykDraw(){
  const b=$('acc-yk-body');b.textContent='';
  if(ykView==='load')b.append(accEl('div','acc-yk-p','Смотрю, что уже сохранено…'));
  else if(ykView==='set')ykSet(b);
  else if(ykView==='done')ykDone(b);
  else ykStepView(b);
  if(ykView!=='load')ykFoot(b)
}
function ykStepView(b){
  const n=ykStep, total=YK.steps.length+1;
  b.append(accEl('div','acc-stp','Шаг '+n+' из '+total));
  if(n<=YK.steps.length){
    const s=YK.steps[n-1];
    if(ykIOS&&ykStandalone)b.append(accEl('p','acc-yk-p',YK.texts.ios_standalone));
    b.append(accEl('div','acc-yk-t',s.title));
    s.lines.forEach(t=>b.append(accEl('p','acc-yk-p',t)));
    b.append(...ykLinks(s));
    (s.fields||[]).forEach(f=>b.append(...ykField(f)));
    const ck=accEl('label','acc-yk-ok'),box=accEl('input');box.type='checkbox';
    box.onchange=()=>{buzz();ykGo(n+1)};
    ck.append(box,accEl('span','','Готово'));b.append(ck,ykMsgEl())
  }else{
    b.append(accEl('div','acc-yk-t',YK.form.title));
    b.append(accEl('p','acc-yk-p','Три значения: ключ API, Client ID и Client secret. Проверьте, что они на месте.'));
    YK.fields.forEach(f=>b.append(...ykField(f.name)));
    b.append(ykMsgEl());
    b.append(ykBtn('Проверить и сохранить','acc wide',()=>ykSave(false)));
    if(ykSkip)b.append(ykBtn('Сохранить без проверки','wide',()=>ykSave(true)))
  }
  if(n>1)b.append(ykBtn('Назад','sm',()=>ykGo(n-1)))
}
function ykSet(b){
  const full=ykSt&&ykSt.set;
  b.append(accEl('div','acc-yk-big',full?'Ключи заданы (…'+ykSt.last4+')':'Заданы не все три значения'));
  b.append(accEl('p','acc-yk-p',full?'Сами значения здесь не показываются.':'Нажмите «Заменить» и введите их заново или «Удалить».'));
  const row=accEl('div','acc-yk-row');
  if(full)row.append(ykBtn('Проверить','',ykCheck));
  row.append(ykBtn('Заменить','',()=>{ykSay('');ykGo(1)}));
  row.append(ykBtn('Удалить','',()=>{if(armed('acc-yk-del','Точно удалить?'))ykClear()},'acc-yk-del'));
  b.append(row,ykMsgEl());
  if(full)b.append(ykBtn('Войти в YouTube заново','acc wide',ykSignin))
}
function ykDone(b){
  b.append(accEl('div','acc-yk-big','Готово: ключи сохранены (…'+ykLast4+')'));
  if(ykNote)b.append(accEl('p','acc-yk-p',ykNote));
  b.append(accEl('p','acc-yk-p','Со своим ключом вход в YouTube нужно повторить. Старый вход сам не удаляется.'));
  b.append(accEl('p','acc-yk-p','Google может написать, что приложение не проверено: это ваше приложение, продолжайте.'));
  b.append(ykBtn('Войти в YouTube заново','acc wide',ykSignin));
  b.append(ykBtn('Закрыть','wide',ykClose))
}
function ykSignin(){ykClose();accStart('youtube')}
// "Закрыть" ends the wizard (the step is kept for the next «Ключи»); a tap beside the sheet only puts it aside
function ykClose(){ykHidden=false;ykDrop(false);ykTell(0);ykHide()}
function ykAside(){ykHidden=true;ykHide()}
function ykHide(){$('acc-yk').classList.add('hide');ykBanner()}
// on the Accounts tab: an unfinished wizard that is not on screen can be taken up again
function ykBanner(){
  const b=$('acc-yk-cont');if(!b)return;
  const show=ykPending()&&$('acc-yk').classList.contains('hide');
  b.classList.toggle('hide',!show);
  if(show)b.textContent=YK.texts.resume.replace('%d',ykSaved()).replace('%d',YK.steps.length+1)
}
async function ykCall(body,doing){
  if(ykBusy)return null;ykBusy=true;ykSay(doing);
  try{return await accCall('ytkeys',body)}
  catch(e){ykSkip=!!(e.data&&e.data.check==='net');ykSay(e.message,true);if(ykView==='step')ykDraw();return null}
  finally{ykBusy=false}
}
async function ykSave(skip){
  const body={action:'save'};YK.fields.forEach(f=>{body[f.name]=ykIn[f.name].value.trim()});
  if(skip)body.skip_check=true;
  const j=await ykCall(body,'Проверяю ключ и записываю… это может занять до 20 секунд.');
  if(!j)return;
  Object.values(ykIn).forEach(i=>{i.value=''});
  ykSkip=false;ykLast4=j.last4||'';ykNote=j.check==='quota'?j.message:'';ykSt={set:true,last4:ykLast4};
  ykDrop(true);   // finished: nothing to come back to (the panel has already cleared the TV's step)
  ykSay('');ykShow('done');ykBanner();buzz()
}
async function ykCheck(){
  const j=await ykCall({action:'check'},'Проверяю ключ…');
  if(j)ykSay(j.message,!j.works)
}
async function ykClear(){
  const j=await ykCall({action:'clear'},'Удаляю…');
  if(!j)return;
  ykSt={set:false,last4:''};ykSkip=false;ykGo(1);ykSay('Ключи удалены.')
}
// `resume`: the wizard comes back by itself (the page was reloaded, or the phone returned from the browser) or
// from the banner, so it goes to its step even when some of the keys are already there
async function ykOpen(resume){
  if(!resume)buzz();
  ykHidden=false;$('acc-yk').classList.remove('hide');ykBanner();ykSay('');ykShow('load');
  try{
    const j=await accCall('ytkeys',{action:'status'});ykSt=j;
    if(resume&&j.set){ykDrop(true);ykTell(0);ykHide()}   // saved in the meantime (from another phone)
    else if(!resume&&(j.set||j.partial))ykShow('set');
    else ykGo(ykSaved())
  }catch(e){ykSay(e.message,true);ykGo(ykSaved())}
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
