"""The Accounts part of the page: markup, style and script, as strings. No logic worth testing
here; panel_accounts.inject() puts them into the page. Everything is prefixed `acc-` / `acc`
so it cannot collide with the page's own ids, classes and functions. The YouTube keys wizard's
sheet is panel_ytkeys_ui.py; the card's "Ключи" button here opens it."""
import json

SECTION = """<section id="t-acc" data-tab="settings" data-spage="acc" class="hide">
    <div class="card"><h2>Аккаунты</h2>
      <button id="acc-yk-cont" class="btn sm acc wide hide"></button>
      <div id="acc-list" class="acc-list"><div class="cap">Загружаю…</div></div>
    </div>
  </section>"""

# @@HOSTS@@ is filled in with the links' whitelist: one list, kept in panel_accounts.py
TAIL = r"""
<style>
.acc-list{display:block}
.acc-svc{padding:14px 0;border-top:1px solid var(--line)}
.acc-svc:first-child{padding-top:0;border-top:0}
.acc-svc:last-child{padding-bottom:0}
.acc-hd{display:flex;justify-content:space-between;align-items:center;gap:10px}
.acc-hd b{font-size:18px;font-weight:600}
.acc-st{color:var(--dim);font-size:14px;text-align:right}
.acc-chips{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.acc-chip{min-height:44px;padding:0 16px;border-radius:999px;border:1px solid var(--line);background:var(--bg);touch-action:manipulation;user-select:none;-webkit-user-select:none}
.acc-chip:active{background:#fff;color:var(--bg)}
.acc-chip.cur{background:#fff;color:var(--bg);font-weight:600}
.acc-chip small{font-size:13px;opacity:.7;margin-left:6px}
.acc-btns{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.acc-btns .btn{flex:1 1 120px;min-height:48px}
.acc-who{margin-top:12px}
.acc-who b{display:block;font-size:20px;font-weight:600;overflow-wrap:anywhere}
.acc-who small{display:block;margin-top:2px;color:var(--dim);font-size:14px}
.acc-lnk{display:block;margin-top:12px;padding:0;min-height:44px;background:none;border:0;color:var(--dim);font-size:15px;text-align:left}
.acc-ch{margin-top:12px;color:var(--dim);font-size:14px;line-height:1.45}
.acc-ch.warn{color:inherit;background:var(--bg);border:1px solid var(--line);border-radius:14px;padding:12px 14px}
.acc-m{margin-top:10px;color:var(--dim);font-size:14px;min-height:1.4em}
.acc-m.bad{color:var(--bad)}
.acc-box .acc-hd{margin-bottom:12px}
.acc-stp{color:var(--dim);font-size:15px}
.acc-x{background:none;border:0;color:var(--dim);font-size:15px;min-height:44px;padding:0 4px}
.acc-code{font:700 clamp(26px,9vw,40px)/1.1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:.06em;text-align:center;padding:18px 8px;background:var(--bg);border-radius:16px;user-select:all;-webkit-user-select:all;overflow-wrap:anywhere}
.acc-sheet.acc-partner .acc-code{font-size:clamp(40px,14vw,64px);padding:26px 8px}
.acc-box .btn{margin-top:10px}
.acc-hint{margin-top:10px;color:var(--faint);font-size:13px;text-align:center;min-height:1.4em}
.acc-fin{display:none;text-align:center;font-size:20px;font-weight:600;padding:28px 0}
.acc-sheet.acc-end .acc-live{display:none}
.acc-sheet.acc-end .acc-fin{display:block}
.acc-mini{display:none;width:calc(100% - 24px);max-width:416px;min-height:52px;align-items:center;justify-content:space-between;gap:10px;padding:0 18px;border:0;border-radius:16px;background:#fff;color:var(--bg);font-weight:600;box-shadow:0 6px 24px rgba(0,0,0,.4)}
.acc-sheet.acc-min{inset:auto 0 calc(76px + env(safe-area-inset-bottom)) 0;pointer-events:none}
.acc-sheet.acc-min .acc-back,.acc-sheet.acc-min .acc-box{display:none}
.acc-sheet.acc-min .acc-mini{display:flex;pointer-events:auto}
@media (min-width:900px){
  #t-acc{grid-area:acc}
  .acc-list{display:grid;grid-template-columns:1fr 1fr;gap:20px}
  .acc-svc,.acc-svc:first-child,.acc-svc:last-child{padding:0;border-top:0}
  .acc-sheet.acc-min{inset:auto 0 16px 0}
}
</style>
<div id="acc-sheet" class="sheet acc-sheet hide" role="dialog" aria-live="polite" aria-label="Вход в аккаунт">
  <div class="sheet-back acc-back" id="acc-back"></div>
  <div class="sheet-box acc-box">
    <div class="acc-hd"><b id="acc-ttl"></b><span id="acc-stp" class="acc-stp"></span><button id="acc-hide" class="acc-x">Свернуть</button></div>
    <div class="acc-live">
      <div id="acc-code" class="acc-code"></div>
      <button id="acc-copy" class="btn wide">Скопировать</button>
      <a id="acc-open" class="btn acc wide" target="_blank" rel="noopener">Открыть страницу входа</a>
      <div id="acc-hint" class="acc-hint"></div>
      <button id="acc-cancel" class="btn wide">Отмена</button>
    </div>
    <div id="acc-fin" class="acc-fin"></div>
  </div>
  <button id="acc-mini" class="acc-mini"><span id="acc-mt"></span><span>Показать</span></button>
</div>
<script>
// ---- accounts: sign in once on the phone, the code is already in the link ----
const ACC_HOSTS=@@HOSTS@@;
const accEl=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e};
const ACC_NO_CHANNEL='У этого аккаунта Google нет канала YouTube, поэтому на ТВ пусто в «Подписках», «Смотреть позже» и «Плейлистах» (рекомендации и поиск работают). '
  +'Создайте канал в приложении YouTube: аватар → «Создать канал». Надпись пропадёт сама; если на ТВ всё ещё пусто — «Выйти» и «Войти». '
  +'Или «Войти другим аккаунтом».';
function accSafe(u){   // only https links to the sign-in pages themselves
  try{const x=new URL(u);return x.protocol==='https:'&&!x.username&&!x.password&&x.port===''&&ACC_HOSTS.indexOf(x.hostname)>=0?x.href:''}catch(e){return ''}
}
async function accCall(what,body){
  let r;try{r=await fetch('/api/accounts/'+what,{method:'POST',headers:{'X-Panel':'1','Content-Type':'application/json'},body:JSON.stringify(body)})}
  catch(e){throw new Error('Нет связи с приставкой')}
  let j={};try{j=await r.json()}catch(e){}
  if(!r.ok||j.ok===false){const e=new Error(j.error||'Не получилось');e.data=j;throw e}   // the reply's other fields stay with the error
  return j
}
let accData=null, accTimer=null, accBusy=false, accKey='', accSheet=null, accCloseT=null, accAsked={}, accSig={};
// a profile's progress: how many of YouTube's four sign-ins it has; SWEET.TV is 0 or 1
const accScore=a=>!a?0:a.service==='youtube'?a.profiles.reduce((n,p)=>n+p.tokens,0):(a.signed_in?1:0);
const accLive=()=>!document.hidden&&(accSheet||(tab==='settings'&&!wide()));
function accLoop(){
  clearTimeout(accTimer);accTimer=null;
  if(accLive())accTimer=setTimeout(accPoll,1500)
}
async function accPoll(){
  if(accBusy)return;accBusy=true;
  try{accApply(await api('/api/accounts'))}catch(e){}
  finally{accBusy=false;accLoop()}
}
// called with the status the page polls anyway: which sign-ins wait (names only)
function accNote(names){
  names=Array.isArray(names)?names:[];const k=names.join(',');
  if(k!==accKey||(names.length&&!accSheet)){accKey=k;accPoll()}
}
function accApply(d){accData=d;accRender(d.accounts||[]);accSync(d);if(window.setRows)setRows()}
// the state of the Аккаунты row in the settings list
function accRowText(){
  const l=(accData&&accData.accounts)||[];
  if(!l.length)return '';
  const yt=l.find(x=>x.service==='youtube'), sw=l.find(x=>x.service==='sweettv');
  const cur=yt&&yt.profiles.find(p=>p.current&&p.signed_in);
  return 'YouTube: '+(cur?accLabel(cur):'не выполнен вход')+' · SWEET.TV: '+(sw&&sw.signed_in?'вошли':'нет')
}

// ---- the cards ----
function accCard(svc){
  let c=$('acc-c-'+svc);if(c)return c;
  c=accEl('div','acc-svc');c.id='acc-c-'+svc;c.dataset.svc=svc;
  const hd=accEl('div','acc-hd');hd.append(accEl('b','', ''),accEl('span','acc-st'));
  const chips=accEl('div','acc-chips');
  const btns=accEl('div','acc-btns');
  const bin=accEl('button','btn','Войти'),bother=accEl('button','btn','Войти другим аккаунтом'),bout=accEl('button','btn','Выйти');
  const bpar=accEl('button','btn','Через Friendly Share');   // SWEET.TV only: the code is typed into the Friendly Share page by hand
  const bkeys=accEl('button','acc-lnk','Ключи Google ›');   // YouTube only: the Google keys wizard (panel_ytkeys_ui.py), needed once
  bin.dataset.k='in';bother.dataset.k='another';bout.dataset.k='out';bpar.dataset.k='partner';bkeys.dataset.k='keys';bout.id='acc-out-'+svc;
  bin.onclick=()=>accStart(svc);bpar.onclick=()=>accStart(svc,'partner');bkeys.onclick=()=>ykOpen();bother.onclick=()=>accAnother(svc);
  bout.onclick=()=>{if(armed(bout.id,'Нажмите ещё раз, чтобы выйти'))accOut(svc)};
  btns.append(bin,bother,bpar,bout);
  const who=accEl('div','acc-who hide');who.append(accEl('b'),accEl('small'));
  c.append(hd,who,accEl('div','acc-ch hide'),chips,btns,accEl('div','acc-m'),bkeys);
  $('acc-list').append(c);return c
}
function accMsg(svc,t,bad){const m=accCard(svc).querySelector('.acc-m');m.textContent=t||'';m.classList.toggle('bad',!!bad)}
function accRender(list){
  const box=$('acc-list');if(box.querySelector('.cap'))box.textContent='';
  list.forEach(a=>{
    const sig=JSON.stringify([a.profiles,a.signed_in,!!(a.signin&&a.signin.state==='waiting'),a.signin&&a.signin.mode]);
    const c=accCard(a.service);
    if(accSig[a.service]===sig)return;accSig[a.service]=sig;
    const yt=a.service==='youtube', cur=a.profiles.find(p=>p.current), waiting=!!(a.signin&&a.signin.state==='waiting');
    const byPartner=waiting&&a.signin.mode==='partner';
    c.querySelector('.acc-hd b').textContent=a.name;
    // YouTube: the profile on the TV is who is signed in; any of the add-on's tokens is enough to watch
    const on=yt?!!(cur&&cur.signed_in):a.signed_in;
    c.querySelector('.acc-st').textContent=byPartner?'ждём подключения':waiting?'ждёт ввода кода':on?'вы вошли':'вход не выполнен';
    const who=c.querySelector('.acc-who');
    who.querySelector('b').textContent=yt&&on?accLabel(cur):'';
    who.querySelector('small').textContent=yt&&on?(cur.channel==='yes'?'Канал YouTube':cur.channel==='no'?'Аккаунт Google без канала':'Аккаунт Google')
      +(a.profiles.length>1&&accLabel(cur)!==cur.name?' · профиль «'+cur.name+'»':''):'';
    who.classList.toggle('hide',!(yt&&on));
    const chips=c.querySelector('.acc-chips');chips.textContent='';
    a.profiles.forEach(p=>{
      const b=accEl('button','acc-chip'+(p.current?' cur':''),accLabel(p));
      if(p.current)b.setAttribute('aria-pressed','true');
      if(!p.signed_in)b.append(accEl('small','','не вошёл'));
      b.onclick=()=>{if(!p.current)accSwitch(a.service,p)};
      chips.append(b)});
    chips.classList.toggle('hide',a.profiles.length<2);   // one account: the line above says it all
    // no YouTube channel on the Google account: Google gives the add-on no subscriptions, Watch Later or playlists
    const ch=c.querySelector('.acc-ch'),cs=yt&&cur&&cur.signed_in?cur.channel:'';
    ch.textContent=cs==='no'?ACC_NO_CHANNEL:'';
    ch.classList.toggle('warn',cs==='no');ch.classList.toggle('hide',!ch.textContent);
    const q=k=>c.querySelector('[data-k='+k+']');
    q('in').classList.toggle('hide',on);q('in').classList.add('acc');q('in').disabled=waiting;
    q('another').classList.toggle('hide',!(yt&&on));q('another').classList.add('acc');q('another').disabled=waiting;
    q('partner').classList.toggle('hide',a.service!=='sweettv'||on);q('partner').disabled=waiting;
    q('keys').classList.toggle('hide',!yt);
    q('out').classList.toggle('hide',!on);
  })
}
async function accRun(svc,what,body,doing,done){
  accMsg(svc,doing);
  try{await accCall(what,body);accMsg(svc,done||'');accAsked[svc]=Date.now();accPoll();return true}
  catch(e){accMsg(svc,e.message,true);return false}
}
async function accStart(svc,mode){
  buzz();
  if(await accRun(svc,'signin',mode?{service:svc,mode}:{service:svc},'Прошу у приставки код…','Жду код от приставки…'))
    setTimeout(()=>{if(!accSheet&&Date.now()-accAsked[svc]>=14000)accMsg(svc,'Код не появился. Посмотрите на телевизор.',true)},15000)
}
function accSwitch(svc,p){buzz();accRun(svc,'switch',{service:svc,id:p.id},'Переключаю на «'+p.name+'»…','Профиль «'+p.name+'» выбран.')}
// a profile's name on the phone: its channel when it has one ("Default" says nothing)
const accLabel=p=>p.channel==='yes'&&p.channel_title?p.channel_title:p.name;
let accBackTo=null;   // the profile to go back to when a sign-in with another account is given up
async function accAnother(svc){
  buzz();accMsg(svc,'Готовлю вход…');
  try{
    const r=await accCall('another',{service:svc});
    if(!r.already)accBackTo=r.previous||null;
    accMsg(svc,'Жду код от приставки…');accAsked[svc]=Date.now();accPoll();
    setTimeout(()=>{if(!accSheet&&Date.now()-accAsked[svc]>=14000)accMsg(svc,'Код не появился. Посмотрите на телевизор.',true)},15000)
  }catch(e){accMsg(svc,e.message,true)}
}
function accOut(svc){accRun(svc,'signout',{service:svc},'Выхожу…','Вы вышли.')}

// ---- the sheet ----
function accOpen(s){
  clearTimeout(accCloseT);accCloseT=null;
  accSheet={svc:s.service,code:'',step:0,score:accScore((accData.accounts||[]).find(x=>x.service===s.service))};
  const sh=$('acc-sheet');sh.classList.remove('hide','acc-min','acc-end');
  $('acc-cancel').disabled=false;$('acc-cancel').textContent='Отмена';
  accShow(s);buzz();accLoop()
}
// a Friendly Share wait (the partner mode) lasts hours: "5 ч 58 мин"; a normal one minutes: "7 мин."
const accLeft=sec=>{const m=Math.ceil(sec/60);return sec<=0?'':m>=60?' Осталось '+Math.floor(m/60)+' ч '+m%60+' мин.':' Осталось '+m+' мин.'};
function accShow(s){
  const was=accSheet.code, partner=s.mode==='partner', link=partner?'':accSafe(s.link), url=partner?'':accSafe(s.url);
  accSheet.mode=s.mode;$('acc-sheet').classList.toggle('acc-partner',partner);
  $('acc-ttl').textContent=s.name;
  $('acc-stp').textContent=s.steps>1?'Код '+s.step+' из '+s.steps:'';
  $('acc-code').textContent=s.code;
  const o=$('acc-open');o.classList.toggle('hide',!link);if(link)o.href=link;
  const left=accLeft(s.left);
  $('acc-hint').textContent=partner?'Скопируйте код и вставьте его в поле «Connection code» на странице Friendly Share, нажмите Save. Не выключайте ТВ на этой странице. Подключают с 14:00 до 00:00.'+left
    :(link?'Страница откроется с уже введённым кодом.':url?'Откройте '+url.replace(/^https:\/\//,'')+' и введите код.':'Введите код на странице входа.')+left;
  $('acc-mt').textContent=s.name+(partner?' · ждём подключения':s.steps>1?' · код '+s.step+' из '+s.steps:' · ждёт код');
  if(was&&(was!==s.code||accSheet.step!==s.step)){   // YouTube moved on to its next code
    $('acc-sheet').classList.remove('acc-min');buzz();
    $('acc-hint').textContent='Новый код: нажмите «Открыть страницу входа» ещё раз.'
  }
  accSheet.code=s.code;accSheet.step=s.step
}
function accEnd(res){
  const sh=$('acc-sheet');
  if(accBackTo&&res!=='done')accCall('switch',{service:'youtube',id:accBackTo}).then(accPoll,()=>{});   // back to who was signed in
  accBackTo=null;
  $('acc-fin').textContent=res==='done'?'Готово — вы вошли':res==='cancelled'?'Отменено':'Не получилось';
  sh.classList.remove('acc-min','acc-partner');sh.classList.add('acc-end');accSheet=null;
  clearTimeout(accCloseT);accCloseT=setTimeout(()=>{sh.classList.add('hide');accCloseT=null;accLoop()},2600);
  if(res==='done')buzz()
}
function accSync(d){
  const w=d.waiting||[];
  if(accSheet){
    const cur=w.find(x=>x.service===accSheet.svc);
    if(cur){accShow(cur);return}
    const a=(d.accounts||[]).find(x=>x.service===accSheet.svc), st=a&&a.signin;
    // a state that vanished (the add-on went away, or we were away too long) counts as done only if the account grew
    accEnd(st&&st.state!=='waiting'?st.state:accScore(a)>accSheet.score?'done':'failed')
  }else if(w.length)accOpen(w[0])
}
$('acc-hide').onclick=()=>$('acc-sheet').classList.add('acc-min');
$('acc-back').onclick=()=>$('acc-sheet').classList.add('acc-min');
$('acc-mini').onclick=()=>$('acc-sheet').classList.remove('acc-min');
$('acc-copy').onclick=()=>{
  const b=$('acc-copy'),el=$('acc-code');buzz();
  copyText(el.textContent).then(ok=>{
    if(!ok){const r=document.createRange();r.selectNodeContents(el);const s=getSelection();s.removeAllRanges();s.addRange(r)}
    b.textContent=ok?'Скопировано':'Выделено — скопируйте вручную';setTimeout(()=>b.textContent='Скопировать',2000)})
};
$('acc-cancel').onclick=async()=>{
  if(!accSheet)return;const b=$('acc-cancel');
  // the code may be about to be typed into the Friendly Share page: the first tap only asks
  if(accSheet.mode==='partner'&&!armed('acc-cancel','Нажмите ещё раз, чтобы отменить'))return;
  b.disabled=true;b.textContent='Отменяю…';
  try{await accCall('cancel',{service:accSheet.svc});accPoll()}
  catch(e){b.disabled=false;b.textContent='Отмена';$('acc-hint').textContent=e.message}
};
document.querySelector('[data-go=settings]').addEventListener('click',accPoll);
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&(accLive()||wide()))accPoll()});
if(wide()||tab==='settings')accPoll();   // the panel's boot has already opened the tab a link or the last visit asked for
</script>
"""


def tail(hosts):
    """The style, the sheet and the script; the script gets the link whitelist as a JSON list."""
    return TAIL.replace("@@HOSTS@@", json.dumps(list(hosts)))
