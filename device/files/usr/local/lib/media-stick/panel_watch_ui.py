"""The Смотреть part of the page: markup, style and script, as strings. No logic worth testing here;
inject() puts them into the panel's page at its four @@WATCH_...@@ markers (the first tab, the section before the
remote's, the remote's bar, the page's tail) and at @@RESUME_ROW@@ (the switch «remember where I stopped» in the
settings list), and raises when one is missing: a page that silently lost the whole tab is worse than one that does
not start. Everything is prefixed `wt` / `wt-` so it
cannot collide with the page's own ids, classes and functions (the page already uses w-ssid, w-btn...).
Pure DOM and fetch; text goes in with textContent, pictures only as https addresses."""

import panel_watch_sweet_ui as sweet

NAV = """<button data-go="watch" class="on"><span class="pb"><svg class="i"><use href="#wt-i-tv"/></svg></span>Смотреть</button>
    """

SECTION = """<section id="t-watch" data-tab="watch">
    <svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
      <symbol id="wt-i-tv" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="12" rx="2"/><path d="M9 21h6M7 3l5 2 5-2"/></symbol>
      <symbol id="wt-i-pause" viewBox="0 0 24 24"><path d="M8 5v14M16 5v14"/></symbol>
      <symbol id="wt-i-search" viewBox="0 0 24 24"><circle cx="11" cy="11" r="7"/><path d="M20 20l-4-4"/></symbol>
    </defs></svg>
    <div class="wt">
      <div data-wtbar class="hide"></div>
      <div id="wt-head" class="wt-head hide"></div>
      <div id="wt-body"></div>
    </div>
  </section>
  <section id="wt-rcard" class="wt-rcoff" data-tab="settings"><label class="card wt-sw"><span class="wt-swt"><b id="wt-rl2"></b><small id="wt-rh2"></small></span><input id="wt-rs2" type="checkbox" role="switch" aria-labelledby="wt-rl2" aria-describedby="wt-rh2"></label></section>
  """

BAR = """<div data-wtbar class="hide"></div>"""

# a row of the settings list: hidden until /api/sweettv/settings answers, then its label and hint are the API's
RESUME_ROW = """<label id="wt-resume" class="srow wt-sw hide"><span class="wt-swt"><b id="wt-rl"></b><small id="wt-rh"></small></span><input id="wt-rs" type="checkbox" role="switch" aria-labelledby="wt-rl" aria-describedby="wt-rh"></label>
      """

CSS = r"""
<style>
.wt{font-family:Inter,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.wt button{font:inherit;color:inherit}
.wt-card{background:var(--card);border:1px solid var(--line);border-radius:22px;padding:16px;margin-bottom:12px;box-shadow:0 8px 24px rgba(0,0,0,.3)}
.wt-head{display:flex;align-items:center;gap:8px;margin-bottom:12px}
.wt-head h2{flex:1;margin:0;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:18px;font-weight:600;letter-spacing:0;text-transform:none;color:#fff}
.wt-btn{display:inline-flex;align-items:center;justify-content:center;gap:8px;min-height:44px;min-width:44px;padding:0 18px;border:0;border-radius:999px;background:var(--card2);color:#fff;font-weight:500;touch-action:manipulation;user-select:none;-webkit-user-select:none}
.wt-btn:active{background:#fff;color:var(--bg)}
.wt-btn.pri{background:#fff;color:var(--bg);font-weight:600}
.wt-btn.pri:active{background:#cfd2dc}
.wt-btn.wide{width:100%}
.wt-btn:disabled{opacity:.4}
.wt-btn.ico{padding:0}
.wt-tiles{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.wt-tile{display:flex;flex-direction:column;align-items:flex-start;gap:12px;min-height:112px;padding:16px;border:1px solid var(--line);border-radius:22px;background:var(--card);text-align:left;touch-action:manipulation}
.wt-tile:active{background:var(--card2)}
.wt-logo{display:flex;align-items:center;justify-content:center;width:44px;height:44px;border-radius:14px;font-weight:700;font-size:20px;color:#fff;flex:none;position:relative;overflow:hidden}
.wt-logo img{display:block;width:100%;height:100%;object-fit:cover;border-radius:inherit}
.wt-tile b{font-weight:600;font-size:16px}
.wt-tile small,.wt-sub{color:var(--dim);font-size:13px}
.wt-chips{display:flex;gap:8px;overflow-x:auto;padding:2px 0 12px;scrollbar-width:none}
.wt-chips::-webkit-scrollbar{display:none}
.wt-chip{flex:none;min-height:44px;padding:0 16px;border-radius:999px;border:1px solid var(--line);background:var(--card);color:#fff;touch-action:manipulation}
.wt-chip.on{background:#fff;color:var(--bg);font-weight:600}
.wt-search{display:flex;gap:8px;margin-bottom:12px}
.wt-search input{flex:1;min-width:0;min-height:48px;border-radius:999px;background:var(--card);border:1px solid var(--line);padding:0 18px;color:#fff}
.wt-list{display:flex;flex-direction:column;gap:10px}
.wt-item{display:flex;gap:12px;align-items:center;width:100%;padding:8px;border:1px solid var(--line);border-radius:18px;background:var(--card);text-align:left;min-height:64px;touch-action:manipulation}
.wt-item:active{background:var(--card2)}
.wt-thumb{position:relative;flex:none;width:128px;aspect-ratio:16/9;border-radius:12px;background:var(--card2) center/cover no-repeat;overflow:hidden}
.wt-thumb i{position:absolute;right:4px;bottom:4px;padding:1px 6px;border-radius:6px;background:rgba(0,0,0,.75);font-size:12px;font-weight:600;line-height:1.5;font-style:normal}
.wt-thumb u{position:absolute;left:0;bottom:0;height:3px;background:#ff5a5a;text-decoration:none}
.wt-ch{flex:none;width:56px;height:56px;border-radius:14px;background:var(--card2) center/contain no-repeat}
.wt-txt{flex:1;min-width:0}
.wt-txt b{display:block;font-weight:600;font-size:15px;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical}
.wt-txt .wt-sub{display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wt-bar{height:4px;border-radius:2px;background:var(--line);margin:6px 0 4px;overflow:hidden}
.wt-bar i{display:block;height:100%;background:#fff}
.wt .wt-go{flex:none;width:48px;height:48px;border-radius:50%;border:0;background:#fff;color:var(--bg);display:flex;align-items:center;justify-content:center}
.wt .wt-go .i{fill:currentColor;stroke:none}
.wt-msg{padding:28px 12px;text-align:center;color:var(--dim)}
.wt-msg b{display:block;color:#fff;font-size:17px;margin-bottom:6px}
.wt-msg .wt-btn{margin-top:14px}
.wt-box{display:flex;flex-direction:column;gap:10px}
.wt-box .wt-thumb{width:100%}
.wt-box h3{margin:4px 0 0;font-size:17px}
.wt-art{flex:none;width:96px;aspect-ratio:16/9;border-radius:12px;background:var(--card2) center/cover no-repeat}
.wt-p .wt-art{width:100%;max-width:360px;margin:0 auto;border-radius:18px}
.wt-p{display:flex;flex-direction:column;gap:14px;color:#fff}
.wt-pt{font-size:20px;font-weight:600;line-height:1.25;text-align:center;overflow-wrap:anywhere}
.wt-ps{text-align:center;color:var(--dim);font-size:14px;margin-top:-8px}
.wt-seek{display:flex;align-items:center;gap:10px;font-size:13px;color:var(--dim);font-variant-numeric:tabular-nums}
.wt-seek input,.wt-vol input{flex:1;min-width:0;padding:0;min-height:44px;border:0;background:transparent;accent-color:#fff}
.wt-tr{display:flex;justify-content:center;align-items:center;gap:14px}
.wt-tr .wt-btn{min-width:64px;min-height:56px}
.wt-tr .wt-btn.pri{width:72px;height:72px;border-radius:50%;padding:0}
.wt-tr .wt-btn.pri .i{fill:currentColor;width:30px;height:30px}
.wt-opts{display:flex;flex-wrap:wrap;gap:8px;justify-content:center}
.wt-vol{display:flex;align-items:center;gap:6px}
.wt-two{display:flex;gap:10px}.wt-two>*{flex:1}
/* the now-playing bar: one line, above the tabs' content; a tap opens the player sheet */
.wt-nb{display:flex;align-items:center;gap:10px;height:64px;margin-bottom:12px;padding:8px 10px 8px 8px;border:1px solid var(--line);border-radius:18px;background:var(--card);cursor:pointer;touch-action:manipulation;user-select:none;-webkit-user-select:none}
.wt-nb:active{background:var(--card2)}
.wt-nb .wt-art{width:72px;height:100%;aspect-ratio:auto;border-radius:10px}
.wt-nb .wt-txt{display:flex;flex-direction:column;gap:6px;justify-content:center}
.wt-nb .wt-txt b{font-size:14px;-webkit-line-clamp:1}
.wt-nb .wt-bar{margin:0}
.wt-nb .wt-btn{flex:none;width:44px;height:44px;min-width:0;padding:0;border-radius:50%}
.wt-nb .wt-btn .i{fill:currentColor}
/* the player sheet */
.wt-pbox .wt-p{gap:12px}
/*@@SWEET_CSS@@*/
/* the switch «remember where I stopped» in the settings list */
.wt-sw{display:flex;align-items:center;gap:12px;cursor:pointer}
.wt-swt{flex:1 1 0;min-width:0}
.wt-swt b{display:block;font-weight:400;font-size:17px}
.wt-swt small{display:block;margin-top:2px;color:var(--faint);font-size:13px;line-height:1.35}
/* the page gives every input width:100% and min-height:52px: the track says its own size, min- and max- both */
.wt-sw input[type=checkbox]{flex:none;position:relative;box-sizing:border-box;width:51px;min-width:51px;height:31px;min-height:31px;max-height:31px;margin:0;padding:0;border:0;border-radius:999px;background:rgba(255,255,255,.22);-webkit-appearance:none;appearance:none;outline:none;transition:background .15s}
.wt-sw input[type=checkbox]::before{content:"";position:absolute;left:-6px;right:-6px;top:-8px;bottom:-8px}
.wt-sw input[type=checkbox]::after{content:"";position:absolute;top:2px;left:2px;width:27px;height:27px;border-radius:50%;background:#fff;box-shadow:0 2px 4px rgba(0,0,0,.35);transition:transform .15s}
.wt-sw input[type=checkbox]:checked{background:var(--ok)}
.wt-sw input[type=checkbox]:checked::after{transform:translateX(20px)}
.wt-sw input[type=checkbox]:focus-visible{box-shadow:0 0 0 3px rgba(255,255,255,.45)}
.wt-sw input[type=checkbox]:disabled{opacity:.5}
/* the same switch as a card of its own, for the wide layout (where the settings list is hidden and every page is a card) */
#wt-rcard{display:none!important}
@media (min-width:900px){
  #wt-rcard{display:block!important;grid-column:1/-1}
  #wt-rcard.wt-rcoff{display:none!important}
  #t-watch{grid-area:watch}
  #t-remote>[data-wtbar]{display:none!important}
  .wt-list{display:grid;grid-template-columns:repeat(auto-fill,minmax(340px,1fr))}
  .wt-tiles{grid-template-columns:repeat(auto-fill,minmax(180px,1fr))}
}
</style>"""

JS = r"""
<script>
(function(){
const NS='http://www.w3.org/2000/svg';
const W={stack:[{t:'apps'}],apps:null,last:null,wait:0,busy:false,chunk:30};
const h=(tag,a,...kids)=>{const e=document.createElement(tag);
  for(const k in (a||{})){const v=a[k];if(v==null||v===false)continue;
    if(k==='class')e.className=v;else if(k==='text')e.textContent=v;
    else if(k.slice(0,2)==='on')e.addEventListener(k.slice(2),v);else e.setAttribute(k,v===true?'':v)}
  for(const c of kids.flat()){if(c==null||c===false)continue;e.append(c.nodeType?c:document.createTextNode(c))}
  return e};
// The icon's shapes are copied in, not referenced with <use>: on the iPhone a <use> built in script inside a list row
// drew nothing, and the channel rows' «Смотреть на ТВ» showed as a blank white circle.
const ico=id=>{const s=document.createElementNS(NS,'svg');s.setAttribute('class','i');s.setAttribute('aria-hidden','true');
  const sym=document.getElementById(id);
  if(sym){s.setAttribute('viewBox',sym.getAttribute('viewBox')||'0 0 24 24');for(const k of sym.children)s.appendChild(k.cloneNode(true))}
  return s};
const tm=s=>{s=Math.max(0,Math.floor(s||0));const H=Math.floor(s/3600),M=Math.floor(s/60)%60,S=s%60;
  return H?H+':'+String(M).padStart(2,'0')+':'+String(S).padStart(2,'0'):M+':'+String(S).padStart(2,'0')};
const picture=u=>/^https:\/\//.test(u||'')?'url("'+u.replace(/["\\()\s]/g,encodeURIComponent)+'")':'';
const errText=e=>{try{return JSON.parse(e.message).error||e.message}catch(_){return e.message}};
const g=p=>api('/api/watch/'+p), pst=(p,b)=>api('/api/watch/'+p,b);
const sg=p=>api('/api/sweettv/'+p), spst=(p,b)=>api('/api/sweettv/'+p,b);
const plural=(n,one,few,many)=>{const m=n%100,k=n%10;return m>10&&m<20?many:k===1?one:k>1&&k<5?few:many};
const norm=s=>String(s==null?'':s).toLowerCase().replace(/ё/g,'е');
const hm=s=>{const d=new Date(s*1000);return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0')};
// the day of a time: «Сегодня», «Вчера», «Завтра», else «23 нояб.»
const REL=['Сегодня','Вчера','Завтра'];
function dayName(s){
  const d=new Date(s*1000),n=new Date(),at=k=>new Date(n.getFullYear(),n.getMonth(),n.getDate()+k).toDateString(),t=d.toDateString();
  return t===at(0)?REL[0]:t===at(-1)?REL[1]:t===at(1)?REL[2]:d.toLocaleDateString('ru',{day:'numeric',month:'short'})}
// «Сегодня 18:30», «Вчера 21:00», «Завтра 00:51», else «23 нояб., 21:00»
function dayTime(s){const n=dayName(s);return n+(REL.includes(n)?' ':', ')+hm(s)}
// «Выйдет завтра в 07:36», «Выйдет 26 нояб. в 06:29»
function airs(s){const n=dayName(s);return 'Выйдет '+(REL.includes(n)?n.toLowerCase():n)+' в '+hm(s)}
function views(n){if(!n)return'';if(n>=1e6)return (n/1e6).toFixed(1).replace('.',',')+' млн просмотров';
  return n>=1e3?Math.round(n/1e3)+' тыс. просмотров':n+' просмотров'}
function sub(it){return [it.channel,views(it.views),it.published?new Date(it.published*1000).toLocaleDateString('ru'):''].filter(Boolean).join(' · ')}
const COLORS=['#e5484d','#3e63dd','#30a46c','#f76b15','#8e4ec6','#12a594','#d6409f'];
const colorOf=s=>{let n=0;for(const c of s)n=(n*31+c.charCodeAt(0))>>>0;return COLORS[n%COLORS.length]};

// ---- the player: one, in a sheet (opened from the bar of «Смотреть» or of «Пульт») ----
function mkPlayer(){
  const P={hold:0,drag:false,open:null,st:null};
  const art=h('div',{class:'wt-art'}),title=h('div',{class:'wt-pt'}),subl=h('div',{class:'wt-ps'});
  const t1=h('span',{text:'0:00'}),t2=h('span',{text:'0:00'});
  const seek=h('input',{type:'range',min:0,max:1,step:1,value:0,'aria-label':'Перемотка'});
  const seekRow=h('div',{class:'wt-seek'},t1,seek,t2);
  seek.addEventListener('input',()=>{P.drag=true;t1.textContent=tm(+seek.value)});
  seek.addEventListener('change',()=>{P.drag=false;P.hold=Date.now()+1500;ctl({op:'seek',to:+seek.value})});
  const pp=h('button',{class:'wt-btn pri','aria-label':'Пауза или воспроизведение',onclick:()=>{buzz();ctl({op:'playpause'})}});
  const rw=h('button',{class:'wt-btn','aria-label':'Назад на 10 секунд',text:'−10',onclick:()=>{buzz();ctl({op:'seek',by:-10})}});
  const ff=h('button',{class:'wt-btn','aria-label':'Вперёд на 10 секунд',text:'+10',onclick:()=>{buzz();ctl({op:'seek',by:10})}});
  const bSub=h('button',{class:'wt-chip',text:'Субтитры',onclick:()=>pick('sub')});
  const bAud=h('button',{class:'wt-chip',text:'Аудио',onclick:()=>pick('aud')});
  const optBox=h('div',{class:'wt-opts hide'});
  const vol=h('input',{type:'range',min:0,max:100,step:1,value:0,'aria-label':'Громкость'});
  vol.addEventListener('input',()=>{P.vdrag=true});
  vol.addEventListener('change',()=>{P.vdrag=false;P.vhold=Date.now()+1500;ctl({op:'volume',level:+vol.value})});
  const vm=h('button',{class:'wt-btn ico','aria-label':'Тише',onclick:()=>ctl({op:'volume',by:-5})},ico('i-vdn'));
  const vp=h('button',{class:'wt-btn ico','aria-label':'Громче',onclick:()=>ctl({op:'volume',by:5})},ico('i-vup'));
  const goLive=h('button',{class:'wt-btn wide hide',text:'К эфиру',onclick:()=>{buzz();spst('golive',{}).then(()=>setTimeout(tick,250)).catch(e=>toast(errText(e)))}});
  const stop=h('button',{class:'wt-btn wide',text:'Остановить',onclick:()=>{buzz();ctl({op:'stop'});toast('Останавливаю…')}});
  const osd=h('button',{class:'wt-btn','data-a':'osd',text:'Меню плеера',onclick:()=>pressKey('osd')});
  const inf=h('button',{class:'wt-btn','data-a':'info',text:'Описание',onclick:()=>pressKey('info')});
  const root=h('div',{class:'wt-p'},art,title,subl,seekRow,
    h('div',{class:'wt-tr'},rw,pp,ff),goLive,h('div',{class:'wt-opts'},bSub,bAud),optBox,
    h('div',{class:'wt-vol'},vm,vol,vp),h('div',{class:'wt-two'},osd,inf),stop);
  function pick(kind){
    P.open=P.open===kind?null:kind;draw()}
  function draw(){
    const st=P.st;optBox.replaceChildren();
    bSub.classList.toggle('on',P.open==='sub');bAud.classList.toggle('on',P.open==='aud');
    if(!st||!P.open){optBox.classList.add('hide');return}
    optBox.classList.remove('hide');
    if(P.open==='sub'){
      optBox.append(h('button',{class:'wt-chip'+(!st.subtitles_on?' on':''),text:'Выкл',onclick:()=>ctl({op:'subtitle',off:true})}));
      st.subtitles.forEach(s=>optBox.append(h('button',{class:'wt-chip'+(st.subtitles_on&&st.subtitle===s.index?' on':''),text:s.name,onclick:()=>ctl({op:'subtitle',index:s.index})})))
    }else st.audio.forEach(s=>optBox.append(h('button',{class:'wt-chip'+(st.audio_index===s.index?' on':''),text:s.name,onclick:()=>ctl({op:'audio',index:s.index})})))
  }
  P.root=root;
  P.update=function(st){
    P.st=st;
    title.textContent=st.title||'Без названия';
    subl.textContent=[st.programme,st.channel&&st.channel!==st.title?st.channel:'',st.live?'В эфире':'',({youtube:'YouTube',sweettv:'SWEET.TV'})[st.app]].filter(Boolean).join(' · ');
    goLive.classList.toggle('hide',!st.go_live);
    art.style.backgroundImage=picture(st.thumb);art.classList.toggle('hide',!picture(st.thumb));   // no picture: no grey box
    pp.replaceChildren(ico(st.speed===0?'i-play':'wt-i-pause'));
    const total=st.total>0&&!st.live;seekRow.classList.toggle('hide',!total);   // live: the player's ~1 minute is not a length
    if(total&&!P.drag&&Date.now()>P.hold){seek.max=Math.floor(st.total);seek.value=Math.floor(st.time);t1.textContent=tm(st.time)}
    t2.textContent=total?tm(st.total):'';
    bSub.classList.toggle('hide',!st.subtitles.length);bAud.classList.toggle('hide',st.audio.length<2);
    if(typeof st.volume==='number'&&!P.vdrag&&Date.now()>(P.vhold||0))vol.value=st.volume;
    draw()};
  return P}
// the answer of a seek on a live SWEET.TV channel says what happened: the archive of the programme plays, or only a note
function ctl(b){return pst('ctl',b).then(r=>{
  if(r&&r.note)toast(r.note);
  if(r&&r.switched==='archive')toast('Перешёл в архив передачи');
  setTimeout(tick,250)}).catch(e=>toast(errText(e)))}

// ---- navigation ----
const body=()=>$('wt-body');
const cur=()=>W.stack[W.stack.length-1];
function go(d){W.stack.push(d);render()}
function back(){if(W.stack.length>1){W.stack.pop();render()}}
function msgCard(state,retry,name){
  const T={needkey:['Сначала настройте ключ','Для '+name+' нужен личный ключ Google. Он настраивается в «Настройки» → «Аккаунты».'],
    signin:['Сначала войдите','Войдите в '+name+' в «Настройки» → «Аккаунты».'],
    error:['Не получилось загрузить','Проверьте сеть и попробуйте ещё раз.'],
    empty:['Здесь пока пусто',''],prompt:['Поиск на YouTube','Введите, что хотите посмотреть.']}[state]||['Не получилось',''];
  const c=h('div',{class:'wt-card wt-msg'},h('b',{text:T[0]}),T[1]);
  if(state==='needkey'||state==='signin')c.append(h('div',{},h('button',{class:'wt-btn pri',text:'Открыть «Аккаунты»',onclick:openAccounts})));
  else if(state==='error')c.append(h('div',{},h('button',{class:'wt-btn pri',text:'Повторить',onclick:retry})));
  return c}
function lazy(list,items,make){
  let n=0;const sentinel=h('div',{style:'height:1px'});list.append(sentinel);
  const more=()=>{const end=Math.min(items.length,n+W.chunk);const frag=document.createDocumentFragment();
    for(;n<end;n++)frag.append(make(items[n]));list.insertBefore(frag,sentinel);if(n>=items.length)io&&io.disconnect()};
  const io=window.IntersectionObserver?new IntersectionObserver(es=>{if(es.some(e=>e.isIntersecting))more()},{rootMargin:'400px'}):null;
  more();if(io&&n<items.length)io.observe(sentinel);else while(n<items.length)more()}
function header(title,extra){
  const hd=$('wt-head');hd.classList.toggle('hide',W.stack.length<2);hd.replaceChildren();
  if(W.stack.length<2)return;
  hd.append(h('button',{class:'wt-btn ico','aria-label':'Назад',onclick:back},ico('i-left')),h('h2',{text:title}),extra||'')}

function render(){
  const d=cur(),b=body();b.replaceChildren();
  if(d.t==='apps')return renderApps(b);
  if(d.t==='yt')return renderYt(b,d);
  if(d.t==='sweet')return renderSweet(b,d);
  if(d.t==='swguide')return renderGuide(b,d);
  if(d.t==='swshow')return renderShow(b,d);
}
function openOnTv(id){return pst('launch',{app:id}).then(()=>toast('Открываю на ТВ…')).catch(e=>toast(errText(e)))}
// the app's own picture in the square; a letter on a colour when it has none or it does not load
function appLogo(a){
  const letter=(a.name||'?').charAt(0).toUpperCase(), box=h('span',{class:'wt-logo',style:'background:'+colorOf(a.id)});
  if(!a.art){box.textContent=letter;return box}
  box.append(h('img',{src:a.art,alt:'',loading:'lazy',onload:()=>{box.style.background='none'},onerror:e=>{e.target.remove();box.textContent=letter}}));
  return box}
async function renderApps(b){
  header('');
  if(!W.apps){b.append(h('div',{class:'wt-msg',text:'Загружаю…'}));
    try{W.apps=(await g('apps')).apps}catch(e){b.replaceChildren(msgCard('error',render,''));return}
    if(cur().t!=='apps')return;b.replaceChildren()}
  const tiles=h('div',{class:'wt-tiles'});
  W.apps.forEach(a=>{const t=h('button',{class:'wt-tile','aria-label':a.name,onclick:()=>{
      if(a.id==='plugin.video.youtube')go({t:'yt',section:'home',q:'',path:'',title:'YouTube',app:a});
      else if(a.id==='plugin.video.sweettv')go({t:'sweet',cat:'all',title:'SWEET.TV',app:a});
      else openOnTv(a.id)}},
    appLogo(a),
    h('b',{text:a.name}),h('small',{text:a.kind==='catalog'?'Выбрать на телефоне':'Откроется на ТВ'}));tiles.append(t)});
  b.append(tiles)}

// ---- YouTube ----
const SECS=[['home','Главная'],['subscriptions','Подписки'],['history','История'],['playlists','Плейлисты']];
function sheet(it){
  const close=()=>s.remove();
  const play=r=>{close();buzz();pst('play',{file:it.file,resume:r}).catch(e=>toast(errText(e)));toast('Открываю на ТВ…');W.wait=Date.now()+25000;W.last=null;openSheet()};
  const s=h('div',{class:'sheet wt-sheet',role:'dialog','aria-label':it.title},h('div',{class:'sheet-back wt-back',onclick:close}),
    h('div',{class:'sheet-box wt-box'},h('div',{class:'wt-thumb',style:'background-image:'+picture(it.thumb)}),
      h('h3',{text:it.title}),h('div',{class:'wt-sub',text:sub(it)}),
      it.resume>=5?h('button',{class:'wt-btn pri wide',text:'Смотреть на ТВ с '+tm(it.resume),onclick:()=>play(it.resume)}):'',
      h('button',{class:it.resume>=5?'wt-btn wide':'wt-btn pri wide',text:it.resume>=5?'С начала':'Смотреть на ТВ',onclick:()=>play(0)}),
      h('button',{class:'wt-btn wide',text:'Закрыть',onclick:close})));
  $('t-watch').append(s);s.querySelector('button').focus()}
function ytCard(it,d){
  const open=()=>it.folder?go({t:'yt',section:d.section,q:'',path:it.file,title:it.title,app:d.app}):sheet(it);
  return h('button',{class:'wt-item',onclick:open},
    h('div',{class:'wt-thumb',style:'background-image:'+picture(it.thumb)},
      it.duration?h('i',{text:tm(it.duration)}):(it.live?h('i',{text:'вживую'}):''),
      it.progress>0?h('u',{style:'width:'+Math.round(it.progress*100)+'%'}):''),
    h('div',{class:'wt-txt'},h('b',{text:it.title}),h('span',{class:'wt-sub',text:it.folder&&it.count?it.count+' видео':sub(it)})))}
async function renderYt(b,d){
  header(d.title,h('button',{class:'wt-btn',text:'Открыть на ТВ',onclick:()=>openOnTv('plugin.video.youtube')}));
  if(!d.path){
    const inp=h('input',{type:'search',placeholder:'Например: новости','aria-label':'Поиск на YouTube',enterkeyhint:'search',value:d.q||''});
    const submit=()=>{const v=inp.value.trim();if(v){d.section='search';d.q=v;render()}};
    inp.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();inp.blur();submit()}});
    b.append(h('div',{class:'wt-search'},inp,h('button',{class:'wt-btn pri ico','aria-label':'Искать',onclick:submit},ico('wt-i-search'))),
      h('div',{class:'wt-chips',role:'tablist'},SECS.map(([k,n])=>h('button',{class:'wt-chip'+(d.section===k?' on':''),role:'tab','aria-selected':d.section===k,text:n,
        onclick:()=>{d.section=k;d.q='';render()}}))))}
  const out=h('div');b.append(out);
  out.append(h('div',{class:'wt-msg',text:'Загружаю…'}));
  const params=new URLSearchParams({section:d.section});if(d.q)params.set('q',d.q);if(d.path)params.set('path',d.path);
  let r;try{r=await g('youtube?'+params)}catch(e){if(cur()===d)out.replaceChildren(msgCard('error',render,'YouTube'));return}
  if(cur()!==d)return;out.replaceChildren();
  if(r.state!=='data'){out.append(msgCard(r.state,render,'YouTube'));return}
  const list=h('div',{class:'wt-list'});out.append(list);
  let items=r.items.slice(),more=r.more,moreBtn=null;
  lazy(list,items,it=>ytCard(it,d));
  if(more){moreBtn=h('button',{class:'wt-btn wide',style:'margin-top:12px',text:'Ещё',onclick:async()=>{
    moreBtn.disabled=true;try{const p=await g('youtube?'+new URLSearchParams({section:d.section,path:more}));
      if(cur()!==d)return;p.items.forEach(it=>list.append(ytCard(it,d)));more=p.more;if(!more)moreBtn.remove()}
    catch(e){toast(errText(e))}moreBtn.disabled=false}});out.append(moreBtn)}
}

//@@SWEET_JS@@

// ---- now playing: a bar (one at the top of «Смотреть», one of «Пульт») and the one player, in a sheet ----
function mkBar(host){
  const art=h('div',{class:'wt-art'}), title=h('b'), fill=h('i'), line=h('div',{class:'wt-bar'},fill);
  const pp=h('button',{class:'wt-btn pri ico','aria-label':'Пауза или воспроизведение',onclick:e=>{e.stopPropagation();buzz();ctl({op:'playpause'})}});
  host.append(h('div',{class:'wt-nb',role:'button',tabindex:'0','aria-label':'Сейчас на ТВ. Открыть плеер',onclick:openSheet,
      onkeydown:e=>{if(e.target===e.currentTarget&&(e.key==='Enter'||e.key===' ')){e.preventDefault();openSheet()}}},
    art,h('div',{class:'wt-txt'},title,line),pp));
  return {update(st){
    host.classList.toggle('hide',!st);if(!st)return;
    title.textContent=st.programme&&st.title?st.title+' · '+st.programme:st.title||'Без названия';
    const pic=picture(st.thumb);art.classList.toggle('hide',!pic);art.style.backgroundImage=pic;
    const pct=st.total>0&&!st.live?Math.min(100,100*st.time/st.total):0;line.classList.toggle('hide',!pct);fill.style.width=pct+'%';
    pp.replaceChildren(ico(st.speed===0?'i-play':'wt-i-pause'))}}}
const sheetOpen=()=>!W.sheet.classList.contains('hide');
function showSheet(){
  const on=!!(W.last&&W.last.playing);
  W.pmsg.classList.toggle('hide',on);W.wp.root.classList.toggle('hide',!on);
  if(on)W.wp.update(W.last)}
function openSheet(){W.sheet.classList.remove('hide');showSheet()}
function closeSheet(){W.sheet.classList.add('hide');W.wait=0}
function applyNow(st){
  W.last=st;window.wtLast=st;if(window.hdrDraw)hdrDraw();
  const on=!!(st&&st.playing);
  document.body.classList.toggle('np',on);   // the remote card is a little shorter under the bar
  W.bars.forEach(b=>b.update(on?st:null));
  if(!sheetOpen())return;
  if(on)W.wait=0;
  if(on||Date.now()<W.wait)showSheet();else closeSheet()}
function tick(){
  if(document.hidden||W.busy||!(wide()||tab==='watch'||tab==='remote'))return;
  W.busy=true;g('now').then(applyNow).catch(()=>{}).finally(()=>{W.busy=false})}

// ---- wiring ----
W.wp=mkPlayer();
W.pmsg=h('div',{class:'wt-msg',text:'Открываю на ТВ…'});
W.sheet=h('div',{class:'sheet wt-sheet wt-psheet hide',role:'dialog','aria-label':'Сейчас на ТВ'},
  h('div',{class:'sheet-back wt-back',onclick:closeSheet}),
  W.pbox=h('div',{class:'sheet-box wt-box wt-pbox'},W.pmsg,W.wp.root,
    h('button',{class:'wt-btn wide',text:'Закрыть',onclick:closeSheet})));
document.body.append(W.sheet);
// a swipe down closes the sheet (not one that starts on a slider, and not while the sheet is scrolled)
let swipeY=null;
W.pbox.addEventListener('touchstart',e=>{swipeY=W.pbox.scrollTop===0&&e.target.type!=='range'?e.touches[0].clientY:null},{passive:true});
W.pbox.addEventListener('touchend',e=>{if(swipeY!==null&&e.changedTouches[0].clientY-swipeY>80)closeSheet();swipeY=null});
W.bars=[...document.querySelectorAll('[data-wtbar]')].map(mkBar);
document.querySelectorAll('[data-go]').forEach(b=>b.addEventListener('click',()=>setTimeout(tick,0)));
setInterval(tick,1500);

// ---- the switch «remember where I stopped»: a row of the settings list (phone) and a card of its own (wide), one state;
// the texts are the API's; no answer: no row, no card ----
async function loadResume(){
  const row=$('wt-resume'),card=$('wt-rcard'),boxes=[$('wt-rs'),$('wt-rs2')].filter(Boolean);
  if(!row||!boxes.length)return;
  const show=on=>{row.classList.toggle('hide',!on);if(card)card.classList.toggle('wt-rcoff',!on)};
  let r;try{r=await sg('settings')}catch(e){show(false);return}
  if(!r||typeof r.local_resume!=='boolean'){show(false);return}
  ['wt-rl','wt-rl2'].forEach(i=>{const e=$(i);if(e)e.textContent=r.label||''});
  ['wt-rh','wt-rh2'].forEach(i=>{const e=$(i);if(e)e.textContent=r.hint||''});
  const set=v=>boxes.forEach(b=>{b.checked=v});
  set(r.local_resume);show(true);
  boxes.forEach(box=>{box.onchange=async()=>{
    const want=box.checked;boxes.forEach(b=>{b.disabled=true});buzz();
    try{const a=await spst('settings',{local_resume:want});set(!!a.local_resume)}
    catch(e){set(!want);toast(errText(e))}
    boxes.forEach(b=>{b.disabled=false})}})}
loadResume();
document.querySelectorAll('[data-go=settings]').forEach(b=>b.addEventListener('click',loadResume));
render();tick();
})();
</script>"""

CSS = CSS.replace("/*@@SWEET_CSS@@*/", sweet.CSS.strip(), 1)
JS = JS.replace("//@@SWEET_JS@@", sweet.JS.strip(), 1)

MARKERS = {"@@WATCH_NAV@@": NAV, "@@WATCH_SECTION@@": SECTION, "@@WATCH_BAR@@": BAR,
           "@@WATCH_TAIL@@": CSS + JS, "@@RESUME_ROW@@": RESUME_ROW}

def inject(page):
    """The page with the Смотреть tab put at its four markers. A marker the page does not have raises ValueError:
    the page must not come out without the tab, or with half of it."""
    for marker in MARKERS:
        if marker not in page:
            raise ValueError("the page has no %s: the Смотреть tab cannot be put in" % marker)
    for marker, text in MARKERS.items():
        page = page.replace(marker, text, 1)
    return page
