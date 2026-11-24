"""The SWEET.TV pages of the Смотреть tab: the three sections (channels, shows and series, films), the guide of a channel,
the page of a show, the sheet that plays an entry. A piece of script and of style that panel_watch_ui.py puts inside its
own (it is one closure: h(), picture(), lazy(), go(), cur()... are that script's). The routes are /api/sweettv/... (README,
«SWEET.TV API»); every text that comes from them (labels, errors, notes) is shown as given. Names are `sw` / `wt-`."""

CSS = r"""
/* SWEET.TV: sections, the guide of a channel, shows, films */
/* the three sections: one row of three equal buttons (a label, its count under it) that always fits the width */
.wt-seg{display:flex;gap:4px;padding:4px;margin-bottom:12px;border-radius:16px;background:var(--card)}
.wt .wt-seg button{flex:1 1 0;min-width:0;min-height:52px;padding:4px 2px;border:0;border-radius:12px;background:transparent;color:#fff;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;font-size:14px;line-height:1.15;text-align:center;touch-action:manipulation}
.wt .wt-seg button small{font-size:13px;color:var(--dim)}
.wt .wt-seg button.on{background:#fff;color:var(--bg);font-weight:600}
.wt .wt-seg button.on small{color:var(--bg);opacity:.7}
/* what is still to come: information, not cards */
.wt-up{display:flex;flex-direction:column}
.wt-uph{margin:10px 4px 0;font-size:13px;color:var(--faint)}
.wt-upr{display:flex;align-items:center;gap:12px;min-height:44px;padding:4px;color:var(--dim);font-size:14px}
.wt-upr time{flex:none;width:48px;font-variant-numeric:tabular-nums;color:var(--faint)}
.wt-upr span{min-width:0;overflow-wrap:anywhere}
.wt-item[role=button]{cursor:pointer}
.wt-dim{opacity:.45}
.wt-h{margin:18px 4px 8px;font-size:13px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--dim)}
.wt-list>.wt-h{grid-column:1/-1;margin:10px 4px 0}
.wt-gt{display:block;font-size:18px;font-weight:600;line-height:1.25;margin:2px 0 4px;overflow-wrap:anywhere}
.wt-acts{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.wt-acts .wt-btn{flex:1 1 auto}
.wt-note{margin:10px 2px 0;color:var(--faint);font-size:13px}
.wt-rowbar{height:3px;border-radius:2px;background:var(--line);margin:6px 0 2px;overflow:hidden}
.wt-rowbar i{display:block;height:100%;background:#ff5a5a}
"""

JS = r"""
// ---- SWEET.TV: sections, the guide of a channel, shows, films ----
const SWSEC=[['channels','Каналы'],['shows','Шоу и сериалы'],['films','Фильмы']];
// an entry is played: the answer is the TV starting; the 404/409 texts are the API's own
function swPlay(b){buzz();spst('play',b).then(()=>{toast('Открываю на ТВ…');W.wait=Date.now()+25000;W.last=null;openSheet()}).catch(e=>toast(errText(e)))}
// a bottom sheet: what it is and the ways to play it ([label, body of play]); the first one is the main one
function swSheet(title,line,acts){
  const close=()=>s.remove();
  const s=h('div',{class:'sheet wt-sheet',role:'dialog','aria-label':title},h('div',{class:'sheet-back wt-back',onclick:close}),
    h('div',{class:'sheet-box wt-box'},h('h3',{text:title}),h('div',{class:'wt-sub',text:line}),
      acts.map(([label,b],i)=>h('button',{class:'wt-btn wide'+(i?'':' pri'),text:label,onclick:()=>{close();swPlay(b)}})),
      h('button',{class:'wt-btn wide',text:'Закрыть',onclick:close})));
  $('t-watch').append(s);s.querySelector('button').focus()}
// a row of a list: a button when it opens something, a plain one (dimmed when it is out of reach) when not
function swRow(o){
  const kids=[o.pic!==undefined?h('div',{class:'wt-ch',style:'background-image:'+picture(o.pic)}):'',
    h('div',{class:'wt-txt'},h('b',{text:o.title||'Без названия'}),(o.subs||[]).filter(Boolean).map(t=>h('span',{class:'wt-sub',text:t})),
      o.pct>0?h('div',{class:'wt-rowbar'},h('i',{style:'width:'+Math.min(100,Math.round(o.pct))+'%'})):'')];
  const cls='wt-item'+(o.dim?' wt-dim':'');
  return o.open?h('button',{class:cls,onclick:o.open},...kids):h('div',{class:cls,'aria-disabled':o.dim?'true':null},...kids)}
// a search field over a list of {title}: case and ё/е do not matter
function swSearch(out,items,ph,make){
  const inp=h('input',{type:'search',placeholder:ph,'aria-label':ph,enterkeyhint:'search',autocomplete:'off'});
  const list=h('div',{class:'wt-list'});out.append(h('div',{class:'wt-search'},inp),list);
  const fill=()=>{
    const q=norm(inp.value.trim()),rows=q?items.filter(it=>norm(it.title).includes(q)):items;
    list.replaceChildren();
    if(!rows.length){list.append(h('div',{class:'wt-msg',text:'Ничего не нашлось'}));return}
    lazy(list,rows,make)};
  inp.addEventListener('input',fill);
  inp.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();inp.blur()}});
  fill()}

// the page: three sections on top (when the stick can count them), the section below
async function renderSweet(b,d){
  header(d.title,h('button',{class:'wt-btn',text:'Открыть на ТВ',onclick:()=>openOnTv('plugin.video.sweettv')}));
  const top=h('div',{class:'wt-seg',role:'tablist'}),out=h('div');b.append(top,out);
  out.append(h('div',{class:'wt-msg',text:'Загружаю…'}));
  let sec=null;try{sec=await sg('sections')}catch(e){}
  if(cur()!==d)return;
  if(!sec||sec.ok!==true){sec=null;top.remove()}   // no sections: the channel list as it was
  const names=(sec&&sec.labels)||{};
  d.sec=sec&&(d.sec==='shows'||d.sec==='films')?d.sec:'channels';
  const show=()=>{
    const tok=d.tok=(d.tok||0)+1,live=()=>cur()===d&&d.tok===tok;   // the last tap wins, an older answer is dropped
    if(sec)top.replaceChildren(...SWSEC.map(([k,n])=>h('button',{class:d.sec===k?'on':'',role:'tab','aria-selected':d.sec===k,
      onclick:()=>{if(d.sec!==k){d.sec=k;show()}}},h('span',{text:names[k]||n}),h('small',{text:String(sec[k]||0)}))));
    out.replaceChildren(h('div',{class:'wt-msg',text:'Загружаю…'}));
    (d.sec==='shows'?swShows:d.sec==='films'?swFilms:swChannels)(out,d,sec,live,show)};
  show()}

// the pictures of the channels by id (the films have none of their own): kept from the channel list, loaded once when it was not
function setIcons(r){if(r&&r.state==='data')W.icons=Object.fromEntries(r.channels.map(c=>[String(c.id),c.icon]))}
function swIcons(){return W.icons?Promise.resolve(W.icons):g('sweettv').then(r=>{setIcons(r);return W.icons||{}}).catch(()=>({}))}
async function swChannels(out,d,sec,live,retry){
  let r;try{r=await g('sweettv')}catch(e){if(live())out.replaceChildren(msgCard('error',retry,'SWEET.TV'));return}
  if(!live())return;out.replaceChildren();
  if(r.state==='signin'){out.append(msgCard('signin',retry,'SWEET.TV'));return}
  if(r.state!=='data'){out.append(msgCard(r.state==='empty'?'empty':'error',retry,'SWEET.TV'));return}
  const chips=h('div',{class:'wt-chips',role:'tablist'}),list=h('div',{class:'wt-list'});out.append(chips,list);
  setIcons(r);
  const genres=sec&&Array.isArray(sec.genres)&&sec.genres.length?sec.genres.map(x=>({key:x.id,name:x.name})):r.categories;
  const cats=[{key:'all',name:'Все'}].concat(genres);
  if(!cats.some(c=>c.key===d.cat))d.cat='all';
  const fill=()=>{
    chips.replaceChildren(...cats.map(c=>h('button',{class:'wt-chip'+(d.cat===c.key?' on':''),role:'tab','aria-selected':d.cat===c.key,text:c.name,onclick:()=>{d.cat=c.key;fill()}})));
    list.replaceChildren();
    lazy(list,r.channels.filter(c=>d.cat==='all'||c.cats.includes(d.cat)),chRow)};
  const play=c=>{buzz();pst('play',{file:c.play}).catch(e=>toast(errText(e)));toast('Открываю на ТВ…');W.wait=Date.now()+25000;W.last=null;openSheet()};
  // the row opens the guide of the channel; its own ▶ plays it live
  function chRow(c){
    const n=c.now,open=()=>go({t:'swguide',cid:c.id,title:c.name});
    return h('div',{class:'wt-item',role:'button',tabindex:'0',onclick:open,
        onkeydown:e=>{if(e.target===e.currentTarget&&(e.key==='Enter'||e.key===' ')){e.preventDefault();open()}}},
      h('div',{class:'wt-ch',style:'background-image:'+picture(c.icon)}),
      h('div',{class:'wt-txt'},h('b',{text:c.name}),
        n?h('span',{class:'wt-sub',text:n.title}):h('span',{class:'wt-sub',text:'Нет программы'}),
        n?h('div',{class:'wt-bar'},h('i',{style:'width:'+n.percent+'%'})):'',
        c.next?h('span',{class:'wt-sub',text:'Далее '+c.next.time+' · '+c.next.title}):''),
      h('button',{class:'wt-go','aria-label':'Смотреть '+c.name+' на ТВ',onclick:e=>{e.stopPropagation();play(c)}},ico('i-play')))}
  fill()}

async function swShows(out,d,sec,live,retry){
  let r;try{r=await sg('shows')}catch(e){if(live())out.replaceChildren(msgCard('error',retry,'SWEET.TV'));return}
  if(!live())return;out.replaceChildren();
  if(!r.items||!r.items.length){out.append(msgCard('empty'));return}
  swSearch(out,r.items,'Найти шоу',it=>swRow({pic:it.thumb||'',title:it.title,
    subs:[it.episodes+' '+plural(it.episodes,'серия','серии','серий')],open:()=>go({t:'swshow',id:it.id,title:it.title})}))}

async function swFilms(out,d,sec,live,retry){
  let r,icons;try{[r,icons]=await Promise.all([sg('films'),swIcons()])}catch(e){if(live())out.replaceChildren(msgCard('error',retry,'SWEET.TV'));return}
  if(!live())return;out.replaceChildren();
  if(!r.items||!r.items.length){out.append(msgCard('empty'));return}
  swSearch(out,r.items,'Найти фильм',it=>{
    const line=[it.channel,dayTime(it.start),it.minutes?it.minutes+' мин':''].filter(Boolean).join(' · '),more=(it.airings||1)-1,ok=it.available!==false;
    return swRow({pic:it.thumb||icons[String(it.cid)]||undefined,title:it.title,subs:[line,more>0?'ещё '+more+' '+plural(more,'показ','показа','показов'):''],dim:!ok,
      open:ok?()=>swSheet(it.title,line,[['Смотреть на ТВ',{cid:it.cid,epg:it.epg,at:'start'}]]):null})})}

// the page of a show: its episodes by season and number
function swEpisode(e,show){
  const ok=!!e.available,name=e.episode>0?'Серия '+e.episode+(e.title?' · '+e.title:''):e.title||'Серия',line=[e.channel,dayTime(e.start)].filter(Boolean).join(' · ');
  return swRow({title:name,subs:[ok?line:airs(e.start)],dim:!ok,
    open:ok?()=>swSheet(show+' · '+name,line,[['Смотреть с начала',{cid:e.cid,epg:e.epg,at:'start'}]]):null})}
async function renderShow(b,d){
  header(d.title);
  const out=h('div');b.append(out);out.append(h('div',{class:'wt-msg',text:'Загружаю…'}));
  let r;try{r=await sg('show?id='+encodeURIComponent(d.id))}catch(e){if(cur()===d)out.replaceChildren(msgCard('error',render,'SWEET.TV'));return}
  if(cur()!==d)return;out.replaceChildren();
  const n=x=>Number(x)||0;
  const eps=(r.episodes||[]).slice().sort((a,z)=>n(a.season)-n(z.season)||(n(a.episode)||1e9)-(n(z.episode)||1e9)||n(a.start)-n(z.start));
  if(!eps.length){out.append(msgCard('empty'));return}
  const seasons=eps.some(e=>n(e.season)>0),rows=[];let last=0;
  eps.forEach(e=>{if(seasons&&n(e.season)>0&&n(e.season)!==last){last=n(e.season);rows.push({head:'Сезон '+last})}rows.push(e)});
  const list=h('div',{class:'wt-list'});out.append(list);
  lazy(list,rows,e=>e.head?h('h3',{class:'wt-h',text:e.head}):swEpisode(e,d.title))}

// the guide of a channel: on now, what was (newest first), what is to come
async function renderGuide(b,d){
  header(d.title);
  const out=h('div');b.append(out);out.append(h('div',{class:'wt-msg',text:'Загружаю…'}));
  let r;try{r=await sg('guide?cid='+encodeURIComponent(d.cid))}catch(e){if(cur()===d)out.replaceChildren(msgCard('error',render,'SWEET.TV'));return}
  if(cur()!==d)return;out.replaceChildren();
  const cu=r.current,now=r.now||Date.now()/1000,cid=r.cid||d.cid,card=h('div',{class:'wt-card'},h('div',{class:'wt-sub',text:'Сейчас'}));
  if(cu){
    const pct=cu.stop>cu.start?Math.max(0,Math.min(100,100*(now-cu.start)/(cu.stop-cu.start))):0;
    card.append(h('b',{class:'wt-gt',text:cu.title||'Без названия'}),h('div',{class:'wt-sub',text:hm(cu.start)+'–'+hm(cu.stop)}),
      h('div',{class:'wt-bar'},h('i',{style:'width:'+pct+'%'})))
  }else card.append(h('div',{class:'wt-gt',text:'Нет программы'}));
  const acts=h('div',{class:'wt-acts'},h('button',{class:'wt-btn pri',text:'Смотреть эфир',onclick:()=>swPlay({cid})}));
  if(cu&&cu.archive)acts.append(h('button',{class:'wt-btn',text:'С начала',onclick:()=>swPlay({cid,epg:cu.id,at:'start'})}));
  if(cu&&cu.resume>0)acts.append(h('button',{class:'wt-btn',text:'Продолжить с '+tm(cu.resume),onclick:()=>swPlay({cid,epg:cu.id,at:'resume'})}));
  card.append(acts);
  if(!r.archive)card.append(h('div',{class:'wt-note',text:'У этого канала нет архива'}));
  out.append(card);
  const past=r.past||[],next=r.next||[];
  if(past.length){
    out.append(h('h3',{class:'wt-h',text:'Ранее'}));
    const list=h('div',{class:'wt-list'});out.append(list);
    lazy(list,past,e=>swRow({title:e.title,subs:[dayTime(e.start)+(e.watched?' · просмотрено':''),e.archive?'':'Нет в архиве'],
      pct:e.resume>0&&e.stop>e.start?100*e.resume/(e.stop-e.start):0,dim:!e.archive,
      open:e.archive?()=>swSheet(e.title,dayTime(e.start)+'–'+hm(e.stop),
        (e.resume>0?[['Продолжить с '+tm(e.resume),{cid,epg:e.id,at:'resume'}]]:[]).concat([['Смотреть с начала',{cid,epg:e.id,at:'start'}]])):null}))}
  if(next.length){
    out.append(h('h3',{class:'wt-h',text:'Далее'}));
    const list=h('div',{class:'wt-up'}),more=h('button',{class:'wt-btn wide',style:'margin-top:12px',text:'Показать ещё',onclick:()=>reveal()});
    let shown=0,day='';
    const reveal=()=>{const end=Math.min(next.length,shown+15);
      for(;shown<end;shown++){
        const e=next[shown],dn=dayName(e.start);
        if(dn!==day){day=dn;list.append(h('div',{class:'wt-uph',text:dn}))}
        list.append(h('div',{class:'wt-upr'},h('time',{text:hm(e.start)}),h('span',{text:e.title||'Без названия'})))}
      if(shown>=next.length)more.remove()};
    out.append(list,more);reveal()}}
"""
