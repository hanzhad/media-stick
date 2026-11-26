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
  <section id="wt-rcard" class="wt-rcoff" data-tab="settings"><div class="card wt-sw wt-qrow"><span class="wt-swt"><b id="wt-rl2">Качество видео</b><small id="wt-rh2">Ограничение разрешения для SWEET.TV</small></span><div class="wt-qseg" id="wt-qseg2" role="radiogroup" aria-label="Качество видео"><button type="button" class="wt-qbtn" data-q="720p">До 720p</button><button type="button" class="wt-qbtn" data-q="1080p">До 1080p (Pi 3)</button><button type="button" class="wt-qbtn" data-q="unlimited">Без лимита / 4K (Pi 5)</button></div></div></section>
  """

BAR = """<div data-wtbar class="hide"></div>"""

# a row of the settings list: video quality cap for SWEET.TV
RESUME_ROW = """<div id="wt-resume" class="srow wt-sw wt-qrow"><span class="wt-swt"><b id="wt-rl">Качество видео</b><small id="wt-rh">Ограничение разрешения для SWEET.TV</small></span><div class="wt-qseg" id="wt-qseg1" role="radiogroup" aria-label="Качество видео"><button type="button" class="wt-qbtn" data-q="720p">До 720p</button><button type="button" class="wt-qbtn" data-q="1080p">До 1080p (Pi 3)</button><button type="button" class="wt-qbtn" data-q="unlimited">Без лимита / 4K (Pi 5)</button></div></div>
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
.wt-seekbox{display:flex;flex-direction:column;gap:4px}
.wt-trow{display:flex;align-items:center;justify-content:space-between;gap:8px;font-size:13px;color:var(--dim);font-variant-numeric:tabular-nums}
.wt-tmid{flex:1;text-align:center;color:#fff;font-weight:500;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wt-tmid.fine{color:#00D2C6;font-weight:700}
.wt-scwrap{position:relative;padding:10px 0}
.wt-track{position:relative;height:32px;display:flex;align-items:center;touch-action:none;cursor:pointer;user-select:none;-webkit-user-select:none}
.wt-rail{position:relative;width:100%;height:6px;border-radius:999px;background:rgba(255,255,255,.18)}
.wt-fill{height:100%;border-radius:999px;background:#fff;width:0%}
.wt-ticks{position:absolute;inset:0;pointer-events:none}
.wt-tick{position:absolute;top:-3px;width:2px;height:12px;margin-left:-1px;border-radius:1px;background:#FFC857}
.wt-knob{position:absolute;top:50%;left:0%;width:18px;height:18px;border-radius:50%;background:#fff;box-shadow:0 2px 6px rgba(0,0,0,.45);transform:translate(-50%,-50%);pointer-events:none}
.wt-bubble{position:absolute;bottom:44px;left:50%;transform:translateX(-50%);display:flex;flex-direction:column;align-items:center;gap:4px;padding:6px 8px;border-radius:12px;background:rgba(12,17,27,.94);border:1px solid rgba(255,255,255,.16);box-shadow:0 8px 20px rgba(0,0,0,.5);pointer-events:none;z-index:8;white-space:nowrap}
.wt-bframe{width:144px;aspect-ratio:16/9;border-radius:8px;background:#1a2336 no-repeat;overflow:hidden}
.wt-btime{font-size:12px;font-weight:600;color:#fff;font-variant-numeric:tabular-nums}
.wt-next{text-align:center;color:var(--dim);font-size:12px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.wt-tapb{text-align:center;font-size:13px;font-weight:700;color:#00D2C6;font-variant-numeric:tabular-nums}
.wt-vol input{flex:1;min-width:0;padding:0;min-height:44px;border:0;background:transparent;accent-color:#fff}
.wt-tr{display:flex;justify-content:center;align-items:center;gap:8px;flex-wrap:nowrap}
.wt-tr .wt-btn{min-width:52px;min-height:52px;padding:0 12px;font-size:14px}
.wt-tr .wt-btn.pri{width:68px;height:68px;min-width:68px;border-radius:50%;padding:0}
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
.wt-dvr{display:flex;flex-wrap:wrap;gap:6px;justify-content:center}
.wt-dvr .wt-btn{min-width:56px;min-height:42px;padding:0 12px;font-size:13px}
.wt-qrow{flex-direction:column;align-items:stretch;gap:8px;cursor:default}
.wt-qseg{display:flex;flex-wrap:wrap;gap:6px}
.wt-qbtn{flex:1 1 auto;min-height:38px;padding:6px 10px;border-radius:12px;border:1px solid var(--line);background:var(--card2);color:#fff;font-size:13px;font-weight:500;touch-action:manipulation}
.wt-qbtn.on{background:#00D2C6;color:#0C111B;border-color:#00D2C6;font-weight:700}
.wt-qbtn:disabled{opacity:.5}
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
  const P={hold:0,drag:false,pid:null,open:null,st:null,min:0,max:1,val:0,mode:'file',
    startX:0,startY:0,fine:false,fineAnchorX:0,fineAnchorVal:0,ring:[],
    thumbs:null,thumbsKey:'',badSheets:{},coalesceTimer:null,coalesceTotal:0};
  const art=h('div',{class:'wt-art'}),title=h('div',{class:'wt-pt'}),subl=h('div',{class:'wt-ps'});
  const t1=h('span',{class:'wt-t1',text:'0:00'}),tMid=h('span',{class:'wt-tmid'}),t2=h('span',{class:'wt-t2',text:'0:00'});
  const fill=h('div',{class:'wt-fill'}),ticksEl=h('div',{class:'wt-ticks'}),rail=h('div',{class:'wt-rail'},fill,ticksEl),knob=h('div',{class:'wt-knob'});
  const bFrame=h('div',{class:'wt-bframe hide'}),bTime=h('div',{class:'wt-btime'}),bubble=h('div',{class:'wt-bubble hide'},bFrame,bTime);
  const track=h('div',{class:'wt-track',role:'slider',tabindex:'0','aria-label':'Перемотка','aria-valuemin':0,'aria-valuemax':1,'aria-valuenow':0},rail,knob);
  const scWrap=h('div',{class:'wt-scwrap'},bubble,track);
  const nextHint=h('div',{class:'wt-next hide'});
  const seekBox=h('div',{class:'wt-seekbox'},h('div',{class:'wt-trow'},t1,tMid,t2),scWrap,nextHint);

  function setVisual(v){
    const span=Math.max(1,P.max-P.min);
    const clamped=Math.max(P.min,Math.min(P.max,v));
    P.val=clamped;
    const pct=(clamped-P.min)*100/span;
    fill.style.width=pct+'%';
    knob.style.left=pct+'%';
    bubble.style.left=Math.max(15,Math.min(85,pct))+'%';
    track.setAttribute('aria-valuemin',String(Math.floor(P.min)));
    track.setAttribute('aria-valuemax',String(Math.floor(P.max)));
    track.setAttribute('aria-valuenow',String(Math.floor(clamped)));
  }
  function updateBubble(v){
    const st=P.st;
    bTime.textContent=(P.mode==='wall'?hm(v):tm(v))+(P.fine?' · Точная подводка ×10':'');
    if(P.mode==='wall'){
      tMid.textContent=P.fine?'Точная подводка ×10':hm(v);
      tMid.classList.toggle('fine',P.fine);
    }else{
      t1.textContent=tm(v);
      tMid.textContent=P.fine?'Точная подводка ×10':'';
      tMid.classList.toggle('fine',P.fine);
    }
    const th=P.thumbs;
    if(th&&th.interval>0&&th.columns>0&&th.rows>0&&th.sheets&&th.sheets.length){
      const base=P.mode==='wall'&&st&&st.prog_start>0?st.prog_start:P.min;
      const offset=Math.max(0,v-base);
      const idx=Math.max(0,Math.floor(offset/th.interval));
      const per=th.rows*th.columns;
      const si=Math.floor(idx/per);
      const rem=idx%per;
      const row=Math.floor(rem/th.columns);
      const col=rem%th.columns;
      const sheetUrl=si<th.sheets.length?th.sheets[si]:'';
      if(sheetUrl&&!P.badSheets[sheetUrl]&&picture(sheetUrl)){
        bFrame.style.backgroundImage=picture(sheetUrl);
        bFrame.style.backgroundSize=(th.columns*100)+'% '+(th.rows*100)+'%';
        bFrame.style.backgroundPosition=(th.columns>1?col*100/(th.columns-1):0)+'% '+(th.rows>1?row*100/(th.rows-1):0)+'%';
        bFrame.classList.remove('hide');
      }else bFrame.classList.add('hide');
    }else bFrame.classList.add('hide');
  }
  track.addEventListener('pointerdown',e=>{
    if(P.max<=P.min)return;
    e.preventDefault();
    try{track.setPointerCapture(e.pointerId)}catch(_){}
    P.drag=true;P.pid=e.pointerId;P.startX=e.clientX;P.startY=e.clientY;P.fine=false;
    const rect=track.getBoundingClientRect();
    const frac=Math.max(0,Math.min(1,(e.clientX-rect.left)/Math.max(1,rect.width)));
    const initVal=P.min+frac*(P.max-P.min);
    P.fineAnchorX=e.clientX;P.fineAnchorVal=initVal;
    P.ring=[{t:Date.now(),v:initVal}];
    setVisual(initVal);updateBubble(initVal);bubble.classList.remove('hide');
  });
  track.addEventListener('pointermove',e=>{
    if(!P.drag||(P.pid!=null&&e.pointerId!==P.pid))return;
    const nowMs=Date.now();
    const dy=Math.abs(e.clientY-P.startY);
    const rect=track.getBoundingClientRect();
    let val;
    if(dy>36){
      if(!P.fine){P.fine=true;P.fineAnchorX=e.clientX;P.fineAnchorVal=P.val}
      val=Math.max(P.min,Math.min(P.max,P.fineAnchorVal+(e.clientX-P.fineAnchorX)*3));
    }else{
      P.fine=false;
      const frac=Math.max(0,Math.min(1,(e.clientX-rect.left)/Math.max(1,rect.width)));
      val=P.min+frac*(P.max-P.min);
    }
    P.ring.push({t:nowMs,v:val});
    while(P.ring.length>1&&nowMs-P.ring[0].t>120)P.ring.shift();
    setVisual(val);updateBubble(val);
  });
  const endDrag=e=>{
    if(!P.drag||(P.pid!=null&&e.pointerId!==P.pid))return;
    P.drag=false;P.pid=null;P.fine=false;P.hold=Date.now()+1500;
    try{track.releasePointerCapture(e.pointerId)}catch(_){}
    bubble.classList.add('hide');tMid.classList.remove('fine');
    if(e.type==='pointercancel')return;
    const cutoff=Date.now()-80;
    let target=P.val;
    for(let i=P.ring.length-1;i>=0;i--){
      if(P.ring[i].t<=cutoff){target=P.ring[i].v;break}
      target=P.ring[i].v;
    }
    target=Math.round(Math.max(P.min,Math.min(P.max,target)));
    if(P.mode==='wall')sctl({op:'seek_wall',wall_ts:target});
    else ctl({op:'seek',to:target});
  };
  track.addEventListener('pointerup',endDrag);
  track.addEventListener('pointercancel',endDrag);

  const tapBadge=h('div',{class:'wt-tapb hide'});
  function pushStep(delta,isSweet){
    buzz();
    P.coalesceTotal+=delta;
    tapBadge.textContent=(P.coalesceTotal>0?'+':'−')+tm(Math.abs(P.coalesceTotal));
    tapBadge.classList.remove('hide');
    clearTimeout(P.coalesceTimer);
    P.coalesceTimer=setTimeout(()=>{
      const sec=P.coalesceTotal;
      P.coalesceTotal=0;
      tapBadge.classList.add('hide');
      if(!sec)return;
      if(isSweet||(P.st&&P.st.app==='sweettv'))sctl({op:'seek_by',seconds:sec});
      else ctl({op:'seek',by:sec});
    },600);
  }

  const pp=h('button',{class:'wt-btn pri','aria-label':'Пауза или воспроизведение',onclick:()=>{buzz();ctl({op:'playpause'})}});
  const bVodBack10=h('button',{class:'wt-btn','aria-label':'Назад на 10 секунд',text:'−10с',onclick:()=>pushStep(-10,false)});
  const bVodPrev=h('button',{class:'wt-btn','aria-label':'Предыдущий эпизод',text:'⏮',onclick:()=>{buzz();sctl({op:'prev_prog'})}});
  const bVodNext=h('button',{class:'wt-btn','aria-label':'Следующий эпизод',text:'⏭',onclick:()=>{buzz();sctl({op:'next_prog'})}});
  const bVodFwd30=h('button',{class:'wt-btn','aria-label':'Вперёд на 30 секунд',text:'+30с',onclick:()=>pushStep(30,false)});
  const bTvBack15=h('button',{class:'wt-btn',text:'−15с',onclick:()=>pushStep(-15,true)});
  const bTvPrev=h('button',{class:'wt-btn',text:'⏮ Пред.',onclick:()=>{buzz();sctl({op:'prev_prog'})}});
  const bTvNext=h('button',{class:'wt-btn',text:'След. ⏭',onclick:()=>{buzz();sctl({op:'next_prog'})}});
  const bTvFwd1m=h('button',{class:'wt-btn',text:'+1м',onclick:()=>pushStep(60,true)});
  const bStart=h('button',{class:'wt-btn',text:'↺ С начала',onclick:()=>{buzz();sctl({op:'from_start'})}});
  const bTvFwd3m=h('button',{class:'wt-btn',text:'+3м',onclick:()=>pushStep(180,true)});
  const bLive=h('button',{class:'wt-btn pri',text:'● В эфир',onclick:()=>{buzz();sctl({op:'live'})}});
  const dvrRow=h('div',{class:'wt-dvr hide'},bStart,bTvFwd3m,bLive);
  const bSub=h('button',{class:'wt-chip',text:'Субтитры',onclick:()=>pick('sub')});
  const bAud=h('button',{class:'wt-chip',text:'Аудио',onclick:()=>pick('aud')});
  const optBox=h('div',{class:'wt-opts hide'});
  const vol=h('input',{type:'range',min:0,max:100,step:1,value:0,'aria-label':'Громкость'});
  vol.addEventListener('input',()=>{P.vdrag=true});
  vol.addEventListener('change',()=>{P.vdrag=false;P.vhold=Date.now()+1500;ctl({op:'volume',level:+vol.value})});
  const vm=h('button',{class:'wt-btn ico','aria-label':'Тише',onclick:()=>ctl({op:'volume',by:-5})},ico('i-vdn'));
  const vp=h('button',{class:'wt-btn ico','aria-label':'Громче',onclick:()=>ctl({op:'volume',by:5})},ico('i-vup'));
  const stop=h('button',{class:'wt-btn wide',text:'Остановить',onclick:()=>{buzz();ctl({op:'stop'});toast('Останавливаю…')}});
  const osd=h('button',{class:'wt-btn','data-a':'osd',text:'Меню плеера',onclick:()=>pressKey('osd')});
  const inf=h('button',{class:'wt-btn','data-a':'info',text:'Описание',onclick:()=>pressKey('info')});
  const root=h('div',{class:'wt-p'},art,title,subl,seekBox,tapBadge,
    h('div',{class:'wt-tr'},bVodBack10,bVodPrev,bTvBack15,bTvPrev,pp,bTvNext,bTvFwd1m,bVodNext,bVodFwd30),
    dvrRow,h('div',{class:'wt-opts'},bSub,bAud),optBox,
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
    const isSw=st.app==='sweettv';
    const isTv=isSw&&!st.is_vod;
    const liveBadge=isTv?(st.time_label||(st.live||st.at_live_edge?'В эфире':(st.lag_seconds>0?'−'+tm(st.lag_seconds)+' от эфира':(st.time>0?'С начала · '+tm(st.time):'')))):(st.live?'В эфире':'');
    subl.textContent=[st.programme,st.channel&&st.channel!==st.title?st.channel:'',liveBadge,({youtube:'YouTube',sweettv:'SWEET.TV'})[st.app]].filter(Boolean).join(' · ');

    bVodBack10.classList.toggle('hide',isTv);
    bVodPrev.classList.toggle('hide',isTv||!st.prev_prog);
    bVodNext.classList.toggle('hide',isTv||!st.next_prog);
    bVodFwd30.classList.toggle('hide',isTv);
    bTvBack15.classList.toggle('hide',!isTv);
    bTvPrev.classList.toggle('hide',!isTv);
    bTvNext.classList.toggle('hide',!isTv);
    bTvFwd1m.classList.toggle('hide',!isTv);
    bTvPrev.disabled=!st.prev_prog;
    bTvNext.disabled=!st.next_prog||!st.next_prog.can_archive;
    dvrRow.classList.toggle('hide',!isTv);
    if(isTv){
      bStart.classList.toggle('hide',!st.can_rewind&&st.live);
      bLive.classList.toggle('hide',!!st.at_live_edge||!st.go_live);
    }

    const tk=st.has_thumbs?[st.app,st.cid,st.epg,st.file].join('|'):'';
    if(!tk){P.thumbsKey='';P.thumbs=null}
    else if(tk!==P.thumbsKey){
      P.thumbsKey=tk;P.thumbs=null;P.badSheets={};
      sg('thumbs').then(t=>{
        if(P.thumbsKey===tk&&t&&Array.isArray(t.sheets)&&t.sheets.length){
          P.thumbs=t;
          t.sheets.forEach(u=>{const im=new Image();im.onerror=()=>{P.badSheets[u]=true};im.src=u});
        }
      }).catch(()=>{});
    }

    art.style.backgroundImage=picture(st.thumb);art.classList.toggle('hide',!picture(st.thumb));   // no picture: no grey box
    pp.replaceChildren(ico(st.speed===0?'i-play':'wt-i-pause'));

    const isWall=st.timeline_mode==='wall'&&st.window_end>st.window_start;
    if(isWall){
      P.mode='wall';P.min=st.window_start;P.max=st.window_end;
      seekBox.classList.remove('hide');
      if(!P.drag&&Date.now()>P.hold){
        const curVal=Math.max(P.min,Math.min(P.max,st.wall_ts||P.min));
        setVisual(curVal);
        t1.textContent=hm(P.min);
        t2.textContent=hm(P.max);
        tMid.textContent=st.time_label||hm(curVal);
        tMid.classList.remove('fine');
      }
      ticksEl.replaceChildren();
      (st.slot_ticks||[]).forEach(t=>{
        if(t>P.min&&t<P.max){
          ticksEl.append(h('i',{class:'wt-tick',style:'left:'+(t-P.min)*100/(P.max-P.min)+'%'}));
        }
      });
      if(st.next_prog&&st.next_prog.title){
        nextHint.textContent='Далее в '+hm(st.next_prog.start)+': '+st.next_prog.title;
        nextHint.classList.remove('hide');
      }else nextHint.classList.add('hide');
    }else{
      P.mode='file';
      const total=st.total>0&&!st.live?st.total:0;
      P.min=0;P.max=total;
      ticksEl.replaceChildren();nextHint.classList.add('hide');
      seekBox.classList.toggle('hide',!(total>0));
      if(total>0&&!P.drag&&Date.now()>P.hold){
        setVisual(st.time||0);
        t1.textContent=tm(st.time||0);
        t2.textContent=tm(total);
        tMid.textContent='';
        tMid.classList.remove('fine');
      }
    }
    bSub.classList.toggle('hide',!st.subtitles.length);bAud.classList.toggle('hide',st.audio.length<2);
    if(typeof st.volume==='number'&&!P.vdrag&&Date.now()>(P.vhold||0))vol.value=st.volume;
    draw()};
  return P}
// the answer of a seek on a live SWEET.TV channel says what happened: the archive of the programme plays, or only a note
function ctl(b){return pst('ctl',b).then(r=>{
  if(r&&r.note)toast(r.note);
  if(r&&r.switched==='archive')toast('Перешёл в архив передачи');
  setTimeout(tick,250)}).catch(e=>toast(errText(e)))}
function sctl(b){return spst('ctl',b).then(r=>{
  if(r&&r.note)toast(r.note);
  if(r&&r.switched==='archive')toast('Перешёл в архив передачи');
  if(r&&r.switched==='live')toast('В эфире');
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
  if(d.t==='swvod')return renderVod(b,d);
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
    const pct=st.timeline_mode==='wall'&&st.window_end>st.window_start?Math.max(0,Math.min(100,100*(st.wall_ts-st.window_start)/(st.window_end-st.window_start))):(st.total>0&&!st.live?Math.min(100,100*st.time/st.total):0);line.classList.toggle('hide',!pct);fill.style.width=pct+'%';
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
W.pbox.addEventListener('touchstart',e=>{swipeY=W.pbox.scrollTop===0&&e.target.type!=='range'&&!e.target.closest('.wt-track')?e.touches[0].clientY:null},{passive:true});
W.pbox.addEventListener('touchend',e=>{if(swipeY!==null&&e.changedTouches[0].clientY-swipeY>80)closeSheet();swipeY=null});
W.bars=[...document.querySelectorAll('[data-wtbar]')].map(mkBar);
document.querySelectorAll('[data-go]').forEach(b=>b.addEventListener('click',()=>setTimeout(tick,0)));
setInterval(tick,1500);

// ---- video quality cap: a row of the settings list (phone) and a card of its own (wide), one state ----
async function loadQuality(){
  const row=$('wt-resume'),card=$('wt-rcard'),btns=[...document.querySelectorAll('.wt-qbtn[data-q]')];
  if(!row||!btns.length)return;
  const set=q=>btns.forEach(b=>b.classList.toggle('on',b.dataset.q===q));
  set('1080p');
  if(card)card.classList.remove('wt-rcoff');
  let curQ='1080p';
  try{const r=await sg('settings');if(r&&r.quality){curQ=r.quality;set(curQ)}}catch(e){}
  btns.forEach(btn=>{btn.onclick=async()=>{
    const want=btn.dataset.q;if(want===curQ)return;
    btns.forEach(b=>{b.disabled=true});buzz();set(want);
    try{const a=await spst('settings',{quality:want});curQ=a.quality||want;set(curQ)}
    catch(e){set(curQ);toast(errText(e))}
    btns.forEach(b=>{b.disabled=false})}})}
loadQuality();
document.querySelectorAll('[data-go=settings]').forEach(b=>b.addEventListener('click',loadQuality));
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
