"""The Accounts part of the page: markup, style and script, as strings. No logic worth testing
here; panel_accounts.inject() puts them into the page. Everything is prefixed `acc-` / `acc`
so it cannot collide with the page's own ids, classes and functions. The YouTube keys wizard's
sheet is panel_ytkeys_ui.py; the card's "Ключи" button here opens it.

The code sheet `#acc-sheet` is the FALLBACK sign-in sheet: a normal sign-in is drawn by the onboarding sheet
(panel_onboarding_ui.py, `#ob-sheet`), and while its document is there this script only watches the sign-in (accTrk) so
the card and the result stay right. The old sheet opens only when there is no document (partner mode, no library)."""
import json

SECTION = """<section id="t-acc" data-tab="settings" data-spage="acc" class="hide">
    <h2 class="acc-title">Приложения</h2>
    <button id="acc-yk-cont" class="btn sm acc wide hide"></button>
    <div id="acc-list" class="acc-list">
      <div id="acc-g-youtube" class="acc-grp">
        <div class="acc-gt">YouTube на ТВ</div>
        <div class="acc-rows hide"></div>
        <div class="acc-note hide">Пустые профили не показываются, приставка использует их сама.</div>
        <div class="acc-help hide"><button type="button" class="acc-hlp" aria-expanded="false">На ТВ пусто в «Подписках»? Как исправить ›</button><div class="acc-ch hide"></div></div>
        <div class="acc-m"></div>
        <div class="acc-rows acc-cfg">
          <button id="acc-keys-row" class="acc-row" type="button" onclick="ykOpen()"><span class="acc-tx"><b>Ключи Google</b><small>для входа в YouTube</small></span><span class="chev" aria-hidden="true">›</span></button>
        </div>
      </div>
      <div id="acc-g-sweettv" class="acc-grp">
        <div class="acc-gt">SWEET.TV</div>
        <div class="acc-rows hide"></div>
        <div class="acc-m"></div>
        <div id="acc-sw-cfg" class="acc-rows acc-cfg">
          <div class="acc-row acc-sw acc-qrow"><span class="acc-swt"><b id="acc-sw-ql">Качество видео</b><small id="acc-sw-qh">Ограничение разрешения для SWEET.TV</small></span><div class="acc-qseg" id="acc-sw-qseg" role="radiogroup" aria-label="Качество видео"><button type="button" class="acc-qbtn" data-q="720p">До 720p</button><button type="button" class="acc-qbtn" data-q="1080p">До 1080p (Pi 3)</button><button type="button" class="acc-qbtn" data-q="unlimited">Без лимита / 4K (Pi 5)</button></div></div>
          <label class="acc-row acc-sw"><span class="acc-swt"><b>Предпросмотр эфира в фоне</b><small>Воспроизводить выбранный канал в фоне при просмотре списка</small></span><input type="checkbox" id="acc-sw-preview" checked></label>
        </div>
      </div>
      <div id="acc-g-out" class="acc-grp hide">
        <div class="acc-gt">Выход</div>
        <div class="acc-rows"></div>
      </div>
    </div>
  </section>"""

# @@HOSTS@@ is filled in with the links' whitelist: one list, kept in panel_accounts.py
TAIL = r"""
<style>
.acc-title{margin:0 6px 14px;font-size:24px;font-weight:600;letter-spacing:0;text-transform:none;color:inherit}
.acc-list{display:block}
.acc-gt{margin:22px 6px 8px;color:var(--dim);font-size:13px;letter-spacing:.04em;text-transform:uppercase}
.acc-grp:first-child .acc-gt{margin-top:0}
.acc-rows{background:var(--card);border-radius:20px;overflow:hidden}
.acc-row{display:flex;align-items:center;gap:12px;width:100%;min-height:60px;padding:8px 16px;background:none;border:0;border-top:1px solid var(--line);color:inherit;font:inherit;font-size:17px;text-align:left;touch-action:manipulation;user-select:none;-webkit-user-select:none}
.acc-row:first-child{border-top:0}
button.acc-row:active{background:var(--card2)}
button.acc-row:disabled{opacity:.5}
button.acc-row.wait:disabled{opacity:1}
.acc-av{flex:none;width:40px;height:40px;border-radius:50%;background:var(--card2);display:flex;align-items:center;justify-content:center;font-size:16px;font-weight:600}
.acc-tx{flex:1 1 0;min-width:0}
.acc-tx b{display:block;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.acc-tx small{display:block;margin-top:1px;color:var(--dim);font-size:14px;line-height:1.3;overflow-wrap:anywhere}
.acc-ck{flex:none;display:flex;color:var(--ok)}
.acc-row.add{color:#7db4ff}
.acc-row.red{color:var(--bad)}
.acc-note{margin:8px 6px 0;color:var(--faint);font-size:13px;line-height:1.4}
.acc-hlp{display:block;margin:6px 0 0;padding:6px;min-height:36px;background:none;border:0;color:var(--dim);font:inherit;font-size:13px;text-align:left}
.acc-ch{margin:0 6px;color:var(--dim);font-size:14px;line-height:1.45}
.acc-m{margin:8px 6px 0;color:var(--dim);font-size:14px;min-height:1.4em}
.acc-m:empty{display:none}
.acc-m.bad{color:var(--bad)}
.acc-cfg{margin-top:8px}
.acc-rows.hide+.acc-note+.acc-help+.acc-m:empty+.acc-cfg,.acc-rows.hide+.acc-m:empty+.acc-cfg{margin-top:0}
.acc-qrow{flex-direction:column;align-items:stretch;gap:8px;cursor:default}
.acc-qseg{display:flex;flex-wrap:wrap;gap:6px}
.acc-qbtn{flex:1 1 auto;min-height:38px;padding:6px 10px;border-radius:12px;border:1px solid var(--line);background:var(--card2);color:#fff;font-size:13px;font-weight:500;touch-action:manipulation}
.acc-qbtn.on{background:#00D2C6;color:#0C111B;border-color:#00D2C6;font-weight:700}
.acc-qbtn:disabled{opacity:.5}
.acc-sw{display:flex;align-items:center;gap:12px;cursor:pointer}
.acc-swt{flex:1 1 0;min-width:0}
.acc-swt b{display:block;font-weight:500;font-size:17px}
.acc-swt small{display:block;margin-top:1px;color:var(--dim);font-size:13px;line-height:1.35}
.acc-sw input[type=checkbox]{flex:none;position:relative;box-sizing:border-box;width:51px;min-width:51px;height:31px;min-height:31px;max-height:31px;margin:0;padding:0;border:0;border-radius:999px;background:rgba(255,255,255,.22);-webkit-appearance:none;appearance:none;outline:none;transition:background .15s}
.acc-sw input[type=checkbox]::before{content:"";position:absolute;left:-6px;right:-6px;top:-8px;bottom:-8px}
.acc-sw input[type=checkbox]::after{content:"";position:absolute;top:2px;left:2px;width:27px;height:27px;border-radius:50%;background:#fff;box-shadow:0 2px 4px rgba(0,0,0,.35);transition:transform .15s}
.acc-sw input[type=checkbox]:checked{background:var(--ok)}
.acc-sw input[type=checkbox]:checked::after{transform:translateX(20px)}
.acc-sw input[type=checkbox]:focus-visible{box-shadow:0 0 0 3px rgba(255,255,255,.45)}
.acc-sw input[type=checkbox]:disabled{opacity:.5}
.acc-hd{display:flex;justify-content:space-between;align-items:center;gap:10px}
.acc-hd b{font-size:18px;font-weight:600}
.acc-box .acc-hd{margin-bottom:12px}
.acc-stp{color:var(--dim);font-size:15px}
.acc-x{background:none;border:0;color:var(--dim);font-size:15px;min-height:44px;padding:0 4px}
.acc-code{font:700 clamp(26px,9vw,40px)/1.1 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;letter-spacing:.06em;text-align:center;padding:18px 8px;background:var(--bg);border-radius:16px;user-select:all;-webkit-user-select:all;overflow-wrap:anywhere}
.acc-box .btn{margin-top:10px}
.acc-hint{margin-top:10px;color:var(--faint);font-size:13px;text-align:center;min-height:1.4em}
.acc-fin{display:none;text-align:center;font-size:20px;font-weight:600;padding:28px 0 8px}
.acc-fin .btn{font-weight:400}
.acc-sheet.acc-end .acc-live{display:none}
.acc-sheet.acc-end .acc-fin{display:block}
.acc-mini{display:none;width:calc(100% - 24px);max-width:416px;min-height:52px;align-items:center;justify-content:space-between;gap:10px;padding:0 18px;border:0;border-radius:16px;background:#fff;color:var(--bg);font-weight:600;box-shadow:0 6px 24px rgba(0,0,0,.4)}
.acc-sheet.acc-min{inset:auto 0 calc(76px + env(safe-area-inset-bottom)) 0;pointer-events:none}
.acc-sheet.acc-min .acc-back,.acc-sheet.acc-min .acc-box{display:none}
.acc-sheet.acc-min .acc-mini{display:flex;pointer-events:auto}
@media (min-width:900px){
  #t-acc{grid-area:acc}
  .acc-list{display:grid;grid-template-columns:1fr 1fr;gap:20px;align-items:start}
  .acc-grp .acc-gt,.acc-grp:first-child .acc-gt{margin-top:0}
  #acc-g-out{grid-column:1/-1}
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
      <button id="acc-renew" class="btn wide hide">Обновить код</button>
      <div id="acc-hint" class="acc-hint"></div>
      <button id="acc-cancel" class="btn wide">Отмена</button>
    </div>
    <div id="acc-fin" class="acc-fin"><div id="acc-fin-t"></div><button id="acc-fin-renew" class="btn acc wide hide">Обновить код</button><button id="acc-fin-close" class="btn wide hide">Закрыть</button></div>
  </div>
  <button id="acc-mini" class="acc-mini"><span id="acc-mt"></span><span>Показать</span></button>
</div>
<script>
// ---- accounts: sign in once on the phone, the code is already in the link ----
const ACC_HOSTS=@@HOSTS@@;
const accEl=(tag,cls,text)=>{const e=document.createElement(tag);if(cls)e.className=cls;if(text!==undefined)e.textContent=text;return e};
const ACC_NO_CHANNEL='У этого аккаунта Google нет канала YouTube, поэтому на ТВ пусто в «Подписках», «Смотреть позже» и «Плейлистах» (рекомендации и поиск работают). '
  +'Создайте канал в приложении YouTube: аватар → «Создать канал». Надпись пропадёт сама; если на ТВ всё ещё пусто — выйдите и войдите снова. '
  +'Или «Добавить аккаунт».';
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
let accData=null, accTimer=null, accBusy=false, accKey='', accSheet=null, accCloseT=null, accAsked={}, accSig={}, accWaiting={}, accFastUntil=0, accExpired={};   // accExpired: a SWEET.TV code that ran out, until a new one is asked for
let accWant={};   // svc: {id,name,busy,at}: the profile the person tapped; its row says "переключаю…" while busy, and the TV is said to be on it only from state the TV confirmed
const accSwId=svc=>accWant[svc]&&accWant[svc].busy?accWant[svc].id:'';
let accTrk=null;   // a sign-in the onboarding sheet draws: {svc, score}; the old sheet stays shut and only its end is handled here
const accShown=()=>accSheet||accTrk;   // some sign-in is on screen: poll often
// a profile's progress: how many of YouTube's four sign-ins it has; SWEET.TV is 0 or 1
const accScore=a=>!a?0:a.service==='youtube'?a.profiles.reduce((n,p)=>n+p.tokens,0):(a.signed_in?1:0);
// polled while the card can be seen: a sheet is open, the settings are open, or the whole panel is on one wide screen
const accLive=()=>!document.hidden&&(accShown()||tab==='settings'||wide());
// after a cancel, a closed sheet or a switch the device changes things on its own (it puts the TV back): look often for a while
const accWatch=ms=>{accFastUntil=Date.now()+ms;accPoll()};
function accLoop(){
  clearTimeout(accTimer);accTimer=null;
  if(accLive())accTimer=setTimeout(accPoll,accShown()||Date.now()<accFastUntil?1500:5000)
}
async function accPoll(){
  if(accBusy)return;accBusy=true;
  try{accApply(await api('/api/accounts'))}catch(e){}
  finally{accBusy=false;accLoop()}
}
// called with the status the page polls anyway: which sign-ins wait (names only)
function accNote(names){
  names=Array.isArray(names)?names:[];const k=names.join(',');
  if(k!==accKey||(names.length&&!accShown())){accKey=k;accPoll()}
}
function accApply(d){accData=d;accRender(d.accounts||[]);accSwitched(d.accounts||[]);accSync(d);if(window.setRows)setRows()}
// the one name of a profile on the phone (rows, avatar, toast, sign-out, the list state): the person's channel when it
// is known, else the profile's own name, where the add-on's first profile, "Default", says nothing
const accName=p=>p.channel_title||(p.name==='Default'?'Основной':p.name);
const accInit=n=>String(n).trim().split(/\s+/).slice(0,2).map(w=>w.charAt(0)).join('').toUpperCase()||'?';
// the state of the Аккаунты row in the settings list
function accRowText(){
  const l=(accData&&accData.accounts)||[];
  if(!l.length)return '';
  const yt=l.find(x=>x.service==='youtube'), sw=l.find(x=>x.service==='sweettv');
  const cur=yt&&yt.profiles.find(p=>p.current&&p.signed_in);
  return 'YouTube: '+(cur?accName(cur):'не выполнен вход')+' · SWEET.TV: '+(sw&&sw.signed_in?'вход выполнен':'нет')
}

// ---- the groups: rows in the look of the settings list, built from /api/accounts ----
const ACC_TICK='<svg class="i" viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
// the groups of the page; each keeps its own message line (.acc-m), which a redraw of the rows leaves alone
const ACC_GROUPS=[['youtube','YouTube на ТВ'],['sweettv','SWEET.TV'],['out','Выход']];
function accBindHelp(g){
  const b=g&&g.querySelector('.acc-hlp'), ch=g&&g.querySelector('.acc-ch');
  if(b&&ch&&!b.onclick)b.onclick=()=>{b.setAttribute('aria-expanded',String(ch.classList.toggle('hide')===false))};
}
function accCard(id){
  let g=$('acc-g-'+id);if(g){if(id==='youtube')accBindHelp(g);return g}
  ACC_GROUPS.forEach(([k,title])=>{
    if($('acc-g-'+k))return;
    const e=accEl('div','acc-grp');e.id='acc-g-'+k;
    e.append(accEl('div','acc-gt',title),accEl('div','acc-rows'));
    if(k==='youtube'){
      const n=accEl('div','acc-note hide','Пустые профили не показываются, приставка использует их сама.');
      // the missing-channel hint: one muted line, the explanation opens under it and closes on a second tap
      const h=accEl('div','acc-help hide'), b=accEl('button','acc-hlp','На ТВ пусто в «Подписках»? Как исправить ›'), ch=accEl('div','acc-ch hide');
      b.type='button';b.setAttribute('aria-expanded','false');
      b.onclick=()=>{b.setAttribute('aria-expanded',String(ch.classList.toggle('hide')===false))};
      h.append(b,ch);e.append(n,h)}
    if(k!=='out')e.append(accEl('div','acc-m'));
    $('acc-list').append(e)});
  return $('acc-g-'+id)
}
function accRow(o){
  const r=accEl(o.go?'button':'div','acc-row'+(o.cls?' '+o.cls:''));
  if(o.go){r.type='button';r.onclick=o.go;if(o.off)r.disabled=true}
  if(o.id)r.id=o.id;
  if(o.av!==undefined)r.append(accEl('span','acc-av',o.av));
  if(o.title){const t=accEl('span','acc-tx');t.append(accEl('b','',o.title));if(o.sub)t.append(accEl('small','',o.sub));r.append(t)}
  else r.textContent=o.text;   // a plain row is only its text, so that armed() can swap it
  if(o.tick){const k=accEl('span','acc-ck');k.innerHTML=ACC_TICK;r.append(k)}
  return r
}
function accMsg(svc,t,bad){const m=accCard(svc).querySelector('.acc-m');m.textContent=t||'';m.classList.toggle('bad',!!bad)}
// who is on the TV: the channel when the add-on knows it
const accSub=p=>p.channel_title?'Канал YouTube':p.channel==='no'?'Аккаунт Google без канала':'Аккаунт Google';
function accFillYouTube(a){
  const g=accCard('youtube'), rows=g.querySelector('.acc-rows');rows.textContent='';
  rows.classList.toggle('hide',!a);
  if(!a){g.querySelector('.acc-note').classList.add('hide');g.querySelector('.acc-help').classList.add('hide');return}
  const cur=a.profiles.find(p=>p.current), waiting=!!(a.signin&&a.signin.state==='waiting');
  const signed=a.profiles.filter(p=>p.signed_in);
  const busy=accSwId(a.service);   // one switch at a time: the TV answers the first, the other rows wait
  signed.forEach(p=>rows.append(accRow({av:accInit(accName(p)),title:accName(p),cls:(p.current?'cur':'')+(busy===p.id?' wait':''),tick:p.current,
    sub:busy===p.id?'переключаю…':p.current?accSub(p):'Нажмите, чтобы включить на ТВ',
    go:p.current?null:()=>accSwitch(a.service,p),off:!!busy})));
  if(cur&&!cur.signed_in)rows.append(accRow({av:'+',title:'Новый аккаунт',sub:'ждёт входа'}));
  rows.append(signed.length?accRow({text:'+ Добавить аккаунт',cls:'add',go:()=>accAnother(a.service),off:waiting||!!busy})
    :accRow({text:'Войти в YouTube',cls:'add',go:()=>accStart(a.service),off:waiting||!!busy}));
  // no YouTube channel on the Google account: Google gives the add-on no subscriptions, Watch Later or playlists
  const ch=g.querySelector('.acc-ch'), none=cur&&cur.signed_in&&cur.channel==='no';
  ch.textContent=none?ACC_NO_CHANNEL:'';g.querySelector('.acc-help').classList.toggle('hide',!none);
  if(!none){ch.classList.add('hide');g.querySelector('.acc-hlp').setAttribute('aria-expanded','false')}
  g.querySelector('.acc-note').classList.toggle('hide',!a.profiles.some(p=>!p.signed_in&&!p.current))
}
function accFillSweet(a){
  const g=accCard('sweettv'), rows=g.querySelector('.acc-rows');rows.textContent='';
  rows.classList.toggle('hide',!a);if(!a)return;
  const waiting=!!(a.signin&&a.signin.state==='waiting');
  if(a.signed_in)rows.append(accRow({title:'Вход выполнен',tick:true}));
  else if(accExpired[a.service])rows.append(accRow({text:'Обновить код',cls:'add',go:()=>accRenew(a.service),off:waiting}));
  else rows.append(accRow({text:waiting?'Ждёт ввода кода':'Войти',cls:'add',go:()=>accStart(a.service),off:waiting}))
}
// the way out, for the services that are signed in
function accFillOut(yt,sw){
  const g=accCard('out'), rows=g.querySelector('.acc-rows');rows.textContent='';
  const cur=yt&&yt.profiles.find(p=>p.current&&p.signed_in), ask='Нажмите ещё раз, чтобы выйти';
  const out=(id,svc,text)=>rows.append(accRow({id,text,cls:'red',go:()=>{if(armed(id,ask))accOut(svc)}}));
  if(cur)out('acc-out-youtube','youtube','Выйти из «'+accName(cur)+'» на ТВ');
  if(sw&&sw.signed_in)out('acc-out-sweettv','sweettv','Выйти из SWEET.TV');
  g.classList.toggle('hide',!rows.children.length)
}
function accRender(list){
  const cap=$('acc-list').querySelector('.cap');if(cap)cap.remove();
  accCard('youtube');
  const sig=JSON.stringify([list.map(a=>[a.service,a.profiles,a.signed_in,!!(a.signin&&a.signin.state==='waiting'),accSwId(a.service)]),accExpired]);
  if(accSig.all===sig)return;accSig.all=sig;
  const yt=list.find(x=>x.service==='youtube'), sw=list.find(x=>x.service==='sweettv');
  accFillYouTube(yt);accFillSweet(sw);accFillOut(yt,sw)
}
async function accRun(svc,what,body,doing,done,say){
  accMsg(svc,doing);
  try{await accCall(what,body);accMsg(svc,done||'');if(say)toast(say);accAsked[svc]=Date.now();accPoll();return true}
  catch(e){accMsg(svc,e.message,true);return false}
}
async function accStart(svc){
  buzz();accExpired[svc]=false;
  if(await accRun(svc,'signin',{service:svc},'Прошу у приставки код…','Жду код от приставки…')){
    accWaiting[svc]=true;
    setTimeout(()=>{if(accWaiting[svc]&&!accShown()&&Date.now()-accAsked[svc]>=14000){accWaiting[svc]=false;accMsg(svc,'Код не появился. Посмотрите на телевизор.',true)}},15000)
  }
}
// The TV switches a profile a moment after it is asked, and the panel answers when it has (its `current`). The check
// mark is the polled current_user and nothing else; "На ТВ: …" is said from that answer or from a later poll, never before.
// A TV that is late (504) still gets it when a poll sees the profile current.
const accChosen=p=>'На ТВ: '+accName(p);
async function accSwitch(svc,p){
  buzz();
  const w=accWant[svc]={id:p.id,busy:true,at:Date.now()};
  accMsg(svc,'Переключаю на «'+accName(p)+'»…');
  accSig.all='';accRender((accData&&accData.accounts)||[]);   // this row says "переключаю…", the others wait
  try{
    const r=await accCall('switch',{service:svc,id:p.id});
    w.busy=false;accMsg(svc,'');
    if(r&&r.current===p.id){delete accWant[svc];toast(accChosen(p))}
    else accMsg(svc,'Телевизор не подтвердил профиль. Посмотрите на ТВ.',true)
  }catch(e){w.busy=false;accMsg(svc,e.message,true)}
  accSig.all='';accRender((accData&&accData.accounts)||[]);
  accAsked[svc]=Date.now();accWatch(20000)
}
// the polled list is the other witness: a profile asked for that the TV took after all
function accSwitched(list){
  list.forEach(a=>{
    const w=accWant[a.service];if(!w||w.busy)return;
    if(Date.now()-w.at>60000){delete accWant[a.service];return}
    const cur=a.profiles.find(p=>p.current);
    if(cur&&cur.id===w.id){delete accWant[a.service];accMsg(a.service,'');toast(accChosen(cur))}
  })
}
async function accAnother(svc){
  buzz();accMsg(svc,'Готовлю вход…');
  try{
    await accCall('another',{service:svc});   // when it is given up the device itself puts the TV back on who was signed in
    accMsg(svc,'Жду код от приставки…');accWaiting[svc]=true;accAsked[svc]=Date.now();accPoll();
    setTimeout(()=>{if(accWaiting[svc]&&!accShown()&&Date.now()-accAsked[svc]>=14000){accWaiting[svc]=false;accMsg(svc,'Код не появился. Посмотрите на телевизор.',true)}},15000)
  }catch(e){accMsg(svc,e.message,true)}
}
function accOut(svc){accRun(svc,'signout',{service:svc},'Выхожу…','','Вы вышли.')}

// «Обновить код»: the running sign-in is asked to get a new code in the same run (the panel waits until it shows). Nothing does
// it by itself: the code may have been typed into another page. From the sheet a second tap is needed (the old code dies).
async function accRenew(svc){
  if(accSheet&&accSheet.svc===svc){
    if(!armed('acc-renew','Нажмите ещё раз, чтобы обновить код'))return;
    accSheet.renew=Date.now();$('acc-renew').disabled=true;$('acc-renew').textContent='Обновляю…'
  }else{accMsg(svc,'Прошу у приставки новый код…');$('acc-fin-t').textContent='Прошу у приставки новый код…'}
  buzz();accExpired[svc]=false;
  try{
    await accCall('renew',{service:svc});
    accAsked[svc]=Date.now();accWaiting[svc]=true;accMsg(svc,'Жду код от приставки…');accPoll()
  }catch(e){
    if(accSheet){accSheet.renew=0;$('acc-renew').disabled=false;$('acc-renew').textContent='Обновить код';$('acc-hint').textContent=e.message}
    else{$('acc-fin-t').textContent=e.message;accMsg(svc,e.message,true)}
  }
}
// ---- the sheet ----
function accOpen(s){
  clearTimeout(accCloseT);accCloseT=null;accExpired[s.service]=false;
  accSheet={svc:s.service,code:'',step:0,renew:0,score:accScore((accData.accounts||[]).find(x=>x.service===s.service))};
  const sh=$('acc-sheet');sh.classList.remove('hide','acc-min','acc-end');
  $('acc-cancel').disabled=false;$('acc-cancel').textContent='Отмена';
  accShow(s);buzz();accLoop()
}
// a SWEET.TV wait lasts hours: "5 ч 58 мин"; YouTube's minutes: "7 мин."
const accLeft=sec=>{const m=Math.ceil(sec/60);return sec<=0?'':m>=60?' Осталось '+Math.floor(m/60)+' ч '+m%60+' мин.':' Осталось '+m+' мин.'};
function accShow(s){
  const was=accSheet.code, link=accSafe(s.link), url=accSafe(s.url);
  $('acc-renew').classList.toggle('hide',s.service!=='sweettv');
  $('acc-ttl').textContent=s.name;
  const cnt=s.rounds>1?'подтверждение '+s.round+' из '+s.rounds:'';   // the one counter: Google's approvals, not the add-on's slots
  $('acc-stp').textContent=cnt?cnt.charAt(0).toUpperCase()+cnt.slice(1):'';
  $('acc-code').textContent=s.code;
  const o=$('acc-open');o.classList.toggle('hide',!link);if(link)o.href=link;
  const left=accLeft(s.left);
  $('acc-hint').textContent=(link&&s.prefilled?'Страница откроется с уже введённым кодом.':url?'Откройте '+url.replace(/^https:\/\//,'')+' и введите код.':'Введите код на странице входа.')+left;
  $('acc-mt').textContent=s.name+(cnt?' · '+cnt:' · ждёт код');
  const moved=was&&(was!==s.code||accSheet.step!==s.step);
  if(moved&&!accSheet.renew){   // YouTube moved on to its next code
    $('acc-sheet').classList.remove('acc-min');buzz();
    $('acc-hint').textContent=link&&s.prefilled?'Новый код: нажмите «Открыть страницу входа» ещё раз.':'Новый код: введите его на странице входа.'
  }
  if(moved&&accSheet.renew){accSheet.renew=0;$('acc-renew').disabled=false;$('acc-renew').textContent='Обновить код';$('acc-sheet').classList.remove('acc-min');buzz()}   // the code asked for has come
  accSheet.code=s.code;accSheet.step=s.step
}
const ACC_EXPIRED='Код устарел, нажмите «Обновить код»';
function accEnd(res,st){
  const sh=$('acc-sheet'), svc=accSheet&&accSheet.svc;
  const expired=res==='failed'&&svc==='sweettv'&&!!st&&st.reason==='expired';   // the code ran out (SWEET.TV said so, or nothing answered)
  if(svc){accWaiting[svc]=false;accMsg(svc,expired?ACC_EXPIRED:'',expired);accExpired[svc]=expired}   // «Жду код…» has no meaning once the sign-in is over
  accWatch(20000);
  $('acc-fin-t').textContent=res==='done'?'Готово — вы вошли':res==='cancelled'?'Отменено':expired?ACC_EXPIRED:'Не получилось';
  $('acc-fin-renew').classList.toggle('hide',!expired);$('acc-fin-close').classList.toggle('hide',!expired);
  sh.classList.remove('acc-min');sh.classList.add('acc-end');accSheet=null;
  clearTimeout(accCloseT);accCloseT=null;
  if(!expired)accCloseT=setTimeout(()=>{sh.classList.add('hide');accCloseT=null;accLoop()},2600);   // an expired one stays until the person chooses
  if(res==='done')buzz()
}
// the onboarding sheet draws this sign-in: the server says so (`guided`: a live sign-in document), and so does the status the
// page polls (status.onboarding); only when neither does, the old sheet is the one to open
function accGuided(s){
  if(s.guided)return true;
  const o=typeof lastStatus!=='undefined'&&lastStatus&&Array.isArray(lastStatus.onboarding)?lastStatus.onboarding:[];
  return o.some(x=>x&&x.service===s.service&&x.flow==='signin'&&(!x.state||x.state==='active'))
}
function accSync(d){
  const w=d.waiting||[];
  if(accSheet){
    const cur=w.find(x=>x.service===accSheet.svc);
    if(cur){accShow(cur);return}
    if(accSheet.renew&&Date.now()-accSheet.renew<20000)return;   // the old sign-in is stopped and the new code is on its way
    const a=(d.accounts||[]).find(x=>x.service===accSheet.svc), st=a&&a.signin;
    // a state that vanished (the add-on went away, or we were away too long) counts as done only if the account grew
    accEnd(st&&st.state!=='waiting'?st.state:accScore(a)>accSheet.score?'done':'failed',st)
  }else if(accTrk){
    if(w.some(x=>x.service===accTrk.svc))return;   // still waiting: the onboarding sheet has it
    const t=accTrk, a=(d.accounts||[]).find(x=>x.service===t.svc), st=a&&a.signin;
    accTrk=null;accSheet={svc:t.svc,code:'',step:0,renew:0,score:t.score};   // it is over: the result and a SWEET.TV code that ran out are told here, as before
    clearTimeout(accCloseT);accCloseT=null;$('acc-sheet').classList.remove('hide','acc-min');
    if(typeof obClose==='function')obClose();
    accEnd(st&&st.state!=='waiting'?st.state:accScore(a)>t.score?'done':'failed',st)
  }else if(w.length){
    const s=w[0];
    if(accGuided(s)){
      accTrk={svc:s.service,score:accScore((d.accounts||[]).find(x=>x.service===s.service))};
      accExpired[s.service]=false;accWaiting[s.service]=false;accMsg(s.service,'');accLoop()
    }else accOpen(s)
  }
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
$('acc-renew').onclick=()=>{if(accSheet)accRenew(accSheet.svc)};
$('acc-fin-renew').onclick=()=>accRenew('sweettv');
$('acc-fin-close').onclick=()=>{$('acc-sheet').classList.add('hide');accLoop()};
$('acc-cancel').onclick=async()=>{
  if(!accSheet)return;const b=$('acc-cancel');
  b.disabled=true;b.textContent='Отменяю…';
  try{await accCall('cancel',{service:accSheet.svc});accWatch(20000)}
  catch(e){b.disabled=false;b.textContent='Отмена';$('acc-hint').textContent=e.message}
};
// ---- SWEET.TV app settings: quality cap & background live preview ----
let accSwState={quality:'1080p',preview_video:true};
function accSwDraw(){
  document.querySelectorAll('#acc-sw-qseg button[data-q]').forEach(b=>b.classList.toggle('on',b.dataset.q===accSwState.quality));
  const pv=$('acc-sw-preview');if(pv)pv.checked=!!accSwState.preview_video;
}
function accSwBusy(on){
  document.querySelectorAll('#acc-sw-qseg button[data-q]').forEach(b=>{b.disabled=on});
  const pv=$('acc-sw-preview');if(pv)pv.disabled=on;
}
async function accSwLoad(){
  if(!$('acc-sw-cfg'))return;
  accSwDraw();
  try{
    const r=await api('/api/sweettv/settings');
    if(r&&r.quality)accSwState.quality=r.quality;
    if(r&&typeof r.preview_video==='boolean')accSwState.preview_video=r.preview_video;
    accSwDraw();
  }catch(e){}
}
async function accSwSave(patch){
  const prev={quality:accSwState.quality,preview_video:accSwState.preview_video};
  accSwState={...prev,...patch};
  accSwDraw();accSwBusy(true);
  try{
    const r=await api('/api/sweettv/settings',patch);
    if(r&&r.quality)accSwState.quality=r.quality;
    if(r&&typeof r.preview_video==='boolean')accSwState.preview_video=r.preview_video;
    accSwDraw();
  }catch(e){
    accSwState=prev;accSwDraw();
    if(typeof toast==='function')toast(tvErr(e));
  }finally{accSwBusy(false)}
}
document.querySelectorAll('#acc-sw-qseg button[data-q]').forEach(b=>{
  b.addEventListener('click',()=>{const q=b.dataset.q;if(q===accSwState.quality)return;buzz();accSwSave({quality:q})});
});
if($('acc-sw-preview'))$('acc-sw-preview').addEventListener('change',e=>{
  buzz();accSwSave({preview_video:!!e.target.checked});
});
accCard('youtube');accSwLoad();
document.querySelector('[data-go=settings]').addEventListener('click',()=>{accPoll();accSwLoad()});
document.addEventListener('visibilitychange',()=>{if(!document.hidden&&(accLive()||wide()))accPoll()});
if(wide()||tab==='settings')accPoll();   // the panel's boot has already opened the tab a link or the last visit asked for
</script>
"""


def tail(hosts):
    """The style, the sheet and the script; the script gets the link whitelist as a JSON list."""
    return TAIL.replace("@@HOSTS@@", json.dumps(list(hosts)))
