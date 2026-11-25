"""The SWEET.TV pages of the Смотреть tab: Netflix-style mobile remote UI, sticky search,
continue/favourites/shows/series/movies/channels, VOD/show detail views, and 7-day channel guide.
A piece of script and of style that panel_watch_ui.py puts inside its own closure.
"""

CSS = r"""
/* SWEET.TV brand palette: dark midnight-navy (#0C111B / #121927) & turquoise (#00D2C6 / #14E0C8) + gold (#FFC857) */
.sw-wrap{--sw-bg:#0C111B;--sw-card:#121927;--sw-acc:#00D2C6;--sw-acc2:#14E0C8;--sw-gold:#FFC857;background:var(--sw-bg);border-radius:20px;padding:10px}
.sw-top{position:sticky;top:0;z-index:5;background:var(--sw-bg);padding:4px 0 8px}
.sw-sbox{display:flex;gap:8px;align-items:center}
.sw-sbox input{flex:1;min-width:0;min-height:46px;border-radius:999px;background:var(--sw-card);border:1px solid rgba(255,255,255,.12);padding:0 16px;color:#fff}
.sw-sbox input:focus{outline:none;border-color:var(--sw-acc)}
.sw-pills{display:flex;gap:8px;overflow-x:auto;padding:8px 0 6px;scrollbar-width:none}
.sw-pills::-webkit-scrollbar{display:none}
.sw-pill{flex:none;min-height:40px;padding:0 14px;border-radius:999px;border:1px solid rgba(255,255,255,.12);background:var(--sw-card);color:#fff;font-size:14px;font-weight:500;touch-action:manipulation}
.sw-pill.on{background:var(--sw-acc);color:#0C111B;border-color:var(--sw-acc);font-weight:700}
.sw-filters{display:flex;gap:8px;margin-bottom:10px}
.sw-filters select{flex:1;min-width:0;min-height:42px;border-radius:12px;background:var(--sw-card);border:1px solid rgba(255,255,255,.12);color:#fff;padding:0 10px;font-size:14px}
.sw-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}
@media (min-width:640px){.sw-grid{grid-template-columns:repeat(3,minmax(0,1fr))}}
.sw-card{position:relative;display:flex;flex-direction:column;border-radius:16px;overflow:hidden;background:var(--sw-card);border:1px solid rgba(255,255,255,.08);text-align:left;padding:0;color:#fff;touch-action:manipulation}
.sw-card:active{transform:scale(.98)}
.sw-poster{position:relative;width:100%;aspect-ratio:16/10;background:#1a2336 center/cover no-repeat}
.sw-badge{position:absolute;left:6px;top:6px;padding:2px 7px;border-radius:6px;background:rgba(12,17,27,.82);color:var(--sw-gold);font-size:11px;font-weight:700}
.sw-fav{position:absolute;right:6px;top:6px;width:34px;height:34px;border-radius:50%;border:0;background:rgba(12,17,27,.72);color:#fff;font-size:16px;display:flex;align-items:center;justify-content:center;touch-action:manipulation}
.sw-fav.on{color:var(--sw-acc2)}
.wt-acts .sw-fav{position:static;width:44px;height:44px;flex:0 0 44px;background:var(--sw-card);border:1px solid rgba(255,255,255,.12)}
.sw-cbody{padding:8px 10px 10px;display:flex;flex-direction:column;gap:3px;min-width:0}
.sw-cbody b{font-size:14px;line-height:1.25;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
.sw-cbody small{font-size:12px;color:var(--dim);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sw-pbar{height:3px;background:rgba(255,255,255,.14);border-radius:2px;overflow:hidden;margin-top:4px}
.sw-pbar i{display:block;height:100%;background:var(--sw-acc)}
.sw-hero{border-radius:18px;overflow:hidden;background:var(--sw-card);border:1px solid rgba(255,255,255,.08);margin-bottom:12px}
.sw-hero-img{width:100%;aspect-ratio:16/9;background:#1a2336 center/cover no-repeat}
.sw-hero-body{padding:14px;display:flex;flex-direction:column;gap:8px}
.sw-hero-body h3{margin:0;font-size:20px;line-height:1.2}
.sw-meta{font-size:13px;color:var(--sw-gold);font-weight:600}
.sw-desc{font-size:14px;line-height:1.45;color:var(--dim)}
.sw-days{display:flex;gap:8px;overflow-x:auto;padding:4px 0 12px;scrollbar-width:none}
.sw-days::-webkit-scrollbar{display:none}
.sw-live-pill{display:inline-block;padding:2px 8px;border-radius:999px;background:var(--sw-gold);color:#0C111B;font-size:12px;font-weight:700;margin-left:6px}
.sw-lag-pill{display:inline-block;padding:2px 8px;border-radius:999px;background:rgba(0,210,198,.16);color:var(--sw-acc2);font-size:12px;font-weight:600;margin-left:6px}
.wt-seg{display:flex;gap:4px;padding:4px;margin-bottom:12px;border-radius:16px;background:var(--sw-card)}
.wt-up{display:flex;flex-direction:column}
.wt-uph{margin:10px 4px 0;font-size:13px;color:var(--faint)}
.wt-upr{display:flex;align-items:center;gap:12px;min-height:44px;padding:4px;color:var(--dim);font-size:14px}
.wt-upr time{flex:none;width:48px;font-variant-numeric:tabular-nums;color:var(--faint)}
.wt-upr span{min-width:0;overflow-wrap:anywhere}
.wt-h{margin:16px 4px 8px;font-size:13px;font-weight:600;letter-spacing:.04em;text-transform:uppercase;color:var(--dim)}
.wt-gt{display:block;font-size:18px;font-weight:600;line-height:1.25;margin:2px 0 4px;overflow-wrap:anywhere}
.wt-acts{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
.wt-acts .wt-btn{flex:1 1 auto}
.wt-note{margin:10px 2px 0;color:var(--faint);font-size:13px}
.wt-rowbar{height:3px;border-radius:2px;background:var(--line);margin:6px 0 2px;overflow:hidden}
.wt-rowbar i{display:block;height:100%;background:#00D2C6}
.wt .wt-btn.pri,.wt .wt-chip.on,.wt .wt-go{background:#00D2C6;color:#0C111B}
"""

JS = r"""
// ---- SWEET.TV: Netflix-style mobile remote UI ----
const SW_TABS=[['continue','Продолжить'],['favs','Избранное'],['shows','Шоу'],['series','Сериалы'],['movies','Фильмы'],['channels','ТВ-каналы']];
function swPlay(b){buzz();spst('play',b).then(()=>{toast('Открываю на ТВ…');W.wait=Date.now()+25000;W.last=null;openSheet()}).catch(e=>toast(errText(e)))}
function swFavBtn(key,meta,initFav){
  let on=!!initFav;
  const btn=h('button',{class:'sw-fav'+(on?' on':''),'aria-label':'В избранное',text:on?'♥':'♡',onclick:e=>{
    e.stopPropagation();buzz();btn.disabled=true;
    spst('favourite',Object.assign({key},meta||{})).then(r=>{on=!!r.favourite;btn.classList.toggle('on',on);btn.textContent=on?'♥':'♡'})
      .catch(err=>toast(errText(err))).finally(()=>{btn.disabled=false})}});
  return btn}
function swCard(o){
  const pct=o.pct>0?Math.min(100,Math.round(o.pct)):0;
  return h('div',{class:'sw-card',role:'button',tabindex:'0',onclick:o.open,
      onkeydown:e=>{if(e.target===e.currentTarget&&(e.key==='Enter'||e.key===' ')){e.preventDefault();o.open()}}},
    h('div',{class:'sw-poster',style:o.pic?'background-image:'+picture(o.pic):''},
      o.badge?h('span',{class:'sw-badge',text:o.badge}):'',
      o.favKey?swFavBtn(o.favKey,{title:o.title,thumb:o.pic||'',meta:o.favMeta},o.fav):''),
    h('div',{class:'sw-cbody'},h('b',{text:o.title||'Без названия'}),
      o.sub?h('small',{text:o.sub}):'',
      pct>0?h('div',{class:'sw-pbar'},h('i',{style:'width:'+pct+'%'})):'',
      o.watched?h('small',{text:'Просмотрено'}):''))}
function swRow(o){
  const kids=[o.pic?h('div',{class:'wt-ch',style:'background-image:'+picture(o.pic)}):'',
    h('div',{class:'wt-txt'},h('b',{text:o.title||'Без названия'}),(o.subs||[]).filter(Boolean).map(t=>h('span',{class:'wt-sub',text:t})),
      o.pct>0?h('div',{class:'wt-rowbar'},h('i',{style:'width:'+Math.min(100,Math.round(o.pct))+'%'})):'')];
  const cls='wt-item'+(o.dim?' wt-dim':'');
  return o.open?h('button',{class:cls,onclick:o.open},...kids):h('div',{class:cls,'aria-disabled':o.dim?'true':null},...kids)}
function swSheet(title,line,acts){
  const close=()=>s.remove();
  const s=h('div',{class:'sheet wt-sheet',role:'dialog','aria-label':title},h('div',{class:'sheet-back wt-back',onclick:close}),
    h('div',{class:'sheet-box wt-box'},h('h3',{text:title}),h('div',{class:'wt-sub',text:line}),
      acts.map(([label,b],i)=>h('button',{class:'wt-btn wide'+(i?'':' pri'),text:label,onclick:()=>{close();swPlay(b)}})),
      h('button',{class:'wt-btn wide',text:'Закрыть',onclick:close})));
  $('t-watch').append(s);s.querySelector('button').focus()}

function swOpenItem(it){
  if(it.kind==='channel'||it.cid&&!it.epg)return go({t:'swguide',cid:it.cid||it.id,title:it.title||it.name});
  if(it.kind==='vod'||it.kind==='series'||it.movie_id)return go({t:'swvod',id:String(it.movie_id||it.id),title:it.title});
  if(it.kind==='show'||it.kind==='show_tv'||String(it.id||'').startsWith('vod:')||String(it.id||'').startsWith('epg:')||String(it.id||'').startsWith('tv:')||String(it.id||'').startsWith('tv_s:'))
    return go({t:'swshow',id:String(it.id),title:it.title});
  if(it.cid&&it.epg)return swPlay({cid:it.cid,epg:it.epg,at:it.pos>0?'resume':'start'});
}

function swSearchResults(out,r,heading){
  const items=r&&r.items||[];
  if(!items.length){out.append(h('div',{class:'wt-msg',text:'Ничего не нашлось'}));return}
  const sShows=items.filter(x=>x.kind==='show_tv'||x.kind==='show');
  const progs=items.filter(x=>x.kind==='programme');
  const vods=items.filter(x=>x.kind==='movie'||x.kind==='series'||x.movie_id);
  const chs=items.filter(x=>x.kind==='channel'||(!x.epg&&x.cid&&!x.movie_id&&x.kind!=='show_tv'));
  if(heading)out.append(h('h3',{class:'wt-h',text:heading}));
  const addGroup=(label,arr,make)=>{if(!arr.length)return;out.append(h('h3',{class:'wt-h',text:label}));const g=h('div',{class:'sw-grid'});arr.forEach(x=>g.append(make(x)));out.append(g)};
  addGroup('Шоу и сериалы',sShows,it=>swCard({pic:it.image_url||it.preview||it.thumb||'',title:it.title,sub:[it.subtitle,it.channel_name||it.channel].filter(Boolean).join(' · '),
    favKey:'show:'+it.id,fav:!!it.favourite,open:()=>go({t:'swshow',id:String(it.id),title:it.title})}));
  addGroup('Фильмы и сериалы',vods,it=>swCard({pic:it.image_url||it.poster||it.thumb||'',title:it.title,badge:it.imdb?String(it.imdb):'',sub:it.year?String(it.year):'',
    favKey:'vod:'+(it.movie_id||it.id),fav:!!it.favourite,open:()=>go({t:'swvod',id:String(it.movie_id||it.id),title:it.title})}));
  addGroup('Передачи',progs,it=>swCard({pic:it.image_url||it.thumb||'',title:it.title,sub:[it.channel_name||it.channel,it.start?dayTime(it.start):''].filter(Boolean).join(' · '),
    open:()=>swPlay({cid:it.cid,epg:it.epg,at:'start'})}));
  addGroup('ТВ-каналы',chs,it=>swCard({pic:it.image_url||it.thumb||'',title:it.title,sub:'Канал',favKey:'ch:'+(it.cid||it.id),fav:!!it.favourite,
    open:()=>go({t:'swguide',cid:String(it.cid||it.id),title:it.title})}));
}

async function renderSweet(b,d){
  header(d.title,h('button',{class:'wt-btn',text:'Открыть на ТВ',onclick:()=>openOnTv('plugin.video.sweettv')}));
  const wrap=h('div',{class:'sw-wrap'}),top=h('div',{class:'sw-top'}),out=h('div');
  const inp=h('input',{type:'search',placeholder:'Поиск фильмов, сериалов, шоу, каналов…','aria-label':'Поиск в SWEET.TV',enterkeyhint:'search',autocomplete:'off',value:d.q||''});
  const clr=h('button',{class:'wt-btn ico'+(d.q?'':' hide'),'aria-label':'Очистить поиск',text:'✕',onclick:()=>{inp.value='';d.q='';clr.classList.add('hide');draw()}});
  const pills=h('div',{class:'wt-seg',role:'tablist'});pills.classList.add('sw-pills');
  top.append(h('div',{class:'sw-sbox'},inp,clr),pills);
  wrap.append(top,out);b.append(wrap);

  let timer=null,topCache=null;
  const runSearch=async q=>{
    const tok=d.stok=(d.stok||0)+1;
    out.replaceChildren(h('div',{class:'wt-msg',text:'Ищу…'}));
    try{const r=await sg('search?q='+encodeURIComponent(q));if(cur()!==d||d.stok!==tok)return;out.replaceChildren();swSearchResults(out,r)}
    catch(e){if(cur()===d&&d.stok===tok)out.replaceChildren(msgCard('error',()=>runSearch(q),'SWEET.TV'))}};
  const showTop=async()=>{
    if(inp.value.trim().length>=2)return;
    out.replaceChildren(h('div',{class:'wt-msg',text:'Загружаю…'}));
    try{topCache=topCache||await sg('top');if(cur()!==d||inp.value.trim().length>=2)return;out.replaceChildren();swSearchResults(out,topCache,'Популярное')}
    catch(e){if(cur()===d)draw()}};
  inp.addEventListener('focus',()=>{if(!inp.value.trim())showTop()});
  inp.addEventListener('input',()=>{
    const q=inp.value.trim();d.q=q;clr.classList.toggle('hide',!q);
    clearTimeout(timer);
    if(!q){draw();return}
    if(q.length<2)return;
    timer=setTimeout(()=>runSearch(q),250)});
  inp.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();inp.blur();const q=inp.value.trim();if(q.length>=2)runSearch(q)}});

  d.sec=d.sec||'continue';
  const draw=()=>{
    const tok=d.tok=(d.tok||0)+1,live=()=>cur()===d&&d.tok===tok;
    pills.replaceChildren(...SW_TABS.map(([k,n])=>h('button',{class:'sw-pill'+(d.sec===k?' on':''),role:'tab','aria-selected':d.sec===k,text:n,
      onclick:()=>{if(d.sec!==k){d.sec=k;inp.value='';d.q='';clr.classList.add('hide');draw()}}})));
    out.replaceChildren(h('div',{class:'wt-msg',text:'Загружаю…'}));
    if(d.sec==='continue')return swHome(out,d,live,draw,'continue');
    if(d.sec==='favs')return swHome(out,d,live,draw,'favourites');
    if(d.sec==='shows')return swShows(out,d,live,draw);
    if(d.sec==='series')return swCatalog(out,d,'series',live,draw);
    if(d.sec==='movies')return swCatalog(out,d,'movies',live,draw);
    return swChannels(out,d,live,draw)};
  if(d.q&&d.q.length>=2)runSearch(d.q);else draw();
}

async function swHome(out,d,live,retry,field){
  let r;try{r=await sg('home')}catch(e){if(live())out.replaceChildren(msgCard('error',retry,'SWEET.TV'));return}
  if(!live())return;out.replaceChildren();
  const items=r[field]||[];
  if(!items.length){out.append(msgCard('empty'));return}
  const grid=h('div',{class:'sw-grid'});
  items.forEach(it=>{
    if(field==='continue'){
      const sub=it.kind==='epg'?[it.channel,tm(it.pos)].filter(Boolean).join(' · '):tm(it.pos)+(it.total?' / '+tm(it.total):'');
      grid.append(swCard({pic:it.thumb||'',title:it.title,sub,pct:it.pct,
        open:()=>it.kind==='vod'?swPlay({movie_id:it.movie_id,episode_id:it.episode_id,start:it.pos}):swPlay({cid:it.cid,epg:it.epg,at:it.pos})}));
    }else{
      const k=String(it.key||'');
      grid.append(swCard({pic:it.thumb||'',title:it.title,favKey:k,fav:true,open:()=>{
        if(k.startsWith('ch:'))return go({t:'swguide',cid:k.slice(3),title:it.title});
        if(k.startsWith('vod:'))return go({t:'swvod',id:k.slice(4),title:it.title});
        if(k.startsWith('show:'))return go({t:'swshow',id:k.slice(5),title:it.title});
      }}));
    }});
  out.append(grid)}

async function swShows(out,d,live,retry){
  let r;try{r=await sg('shows')}catch(e){if(live())out.replaceChildren(msgCard('error',retry,'SWEET.TV'));return}
  if(!live())return;out.replaceChildren();
  const items=r.items||[];
  if(!items.length){out.append(msgCard('empty'));return}
  const grid=h('div',{class:'sw-grid'});out.append(grid);
  lazy(grid,items,it=>swCard({pic:it.thumb||'',title:it.title,
    sub:it.episodes?it.episodes+' '+plural(it.episodes,'серия','серии','серий'):'',
    favKey:'show:'+it.id,fav:!!it.favourite,open:()=>go({t:'swshow',id:it.id,title:it.title})}))}

async function swCatalog(out,d,kind,live,retry){
  const st=d[kind]||(d[kind]={genre:0,sort:1});
  const load=async(offset,append,grid,moreBtn)=>{
    const q='?genre='+st.genre+'&sort='+st.sort+'&offset='+offset+'&limit=30';
    let r;try{r=await (kind==='series'?sg('series'+q):sg('movies'+q))}catch(e){if(live()&&!append)out.replaceChildren(msgCard('error',retry,'SWEET.TV'));else if(append)toast(errText(e));return}
    if(!live())return;
    if(!append){
      out.replaceChildren();
      const gSel=h('select',{'aria-label':'Жанр',onchange:()=>{st.genre=+gSel.value;load(0,false)}});
      gSel.append(h('option',{value:'0',text:'Все жанры'}));
      (r.genres||[]).forEach(g=>gSel.append(h('option',{value:String(g.id),text:g.caption||g.name,selected:Number(g.id)===st.genre})));
      const sSel=h('select',{'aria-label':'Сортировка',onchange:()=>{st.sort=+sSel.value;load(0,false)}});
      (r.sort_modes||[]).forEach(s=>sSel.append(h('option',{value:String(s.id),text:s.caption||s.name,selected:Number(s.id)===st.sort})));
      grid=h('div',{class:'sw-grid'});
      out.append(h('div',{class:'sw-filters'},gSel,sSel),grid);
    }
    const items=r.items||[];
    if(!append&&!items.length){out.append(msgCard('empty'));return}
    items.forEach(it=>grid.append(swCard({pic:it.thumb||'',title:it.title,
      badge:it.imdb?String(it.imdb):'',sub:[it.year,it.genre].filter(Boolean).join(' · '),
      favKey:'vod:'+it.id,fav:!!it.favourite,open:()=>go({t:'swvod',id:String(it.id),title:it.title})})));
    if(moreBtn)moreBtn.remove();
    if(r.has_more){
      const nextOff=offset+items.length;
      const btn=h('button',{class:'wt-btn wide',style:'margin-top:12px',text:'Показать ещё',onclick:()=>{btn.disabled=true;load(nextOff,true,grid,btn)}});
      out.append(btn);
    }};
  await load(0,false)}

async function swChannels(out,d,live,retry){
  let r;try{r=await sg('channels')}catch(e){if(live())out.replaceChildren(msgCard('error',retry,'SWEET.TV'));return}
  if(!live())return;out.replaceChildren();
  const chips=h('div',{class:'wt-chips',role:'tablist'}),list=h('div',{class:'wt-list'});out.append(chips,list);
  const cats=[{id:'all',name:'Все'},{id:'fast',name:'24/7'}].concat(r.categories||[]);
  if(!cats.some(c=>c.id===d.cat))d.cat='all';
  const fill=()=>{
    chips.replaceChildren(...cats.map(c=>h('button',{class:'wt-chip'+(d.cat===c.id?' on':''),role:'tab','aria-selected':d.cat===c.id,text:c.name,onclick:()=>{d.cat=c.id;fill()}})));
    list.replaceChildren();
    const rows=(r.channels||[]).filter(c=>d.cat==='all'||(d.cat==='fast'?c.is_fast_channel:(c.cats||[]).includes(d.cat)));
    lazy(list,rows,c=>{
      const n=c.now,open=()=>go({t:'swguide',cid:c.id,title:c.name});
      return h('div',{class:'wt-item',role:'button',tabindex:'0',onclick:open,
          onkeydown:e=>{if(e.target===e.currentTarget&&(e.key==='Enter'||e.key===' ')){e.preventDefault();open()}}},
        h('div',{class:'wt-ch',style:'background-image:'+picture(c.icon)}),
        h('div',{class:'wt-txt'},h('b',{text:c.name}),
          n?h('span',{class:'wt-sub',text:n.title}):h('span',{class:'wt-sub',text:'Нет программы'}),
          n?h('div',{class:'wt-bar'},h('i',{style:'width:'+n.percent+'%'})):'',
          c.next?h('span',{class:'wt-sub',text:'Далее '+hm(c.next.start)+' · '+c.next.title}):''),
        swFavBtn('ch:'+c.id,{title:c.name,thumb:c.icon},c.favourite),
        h('button',{class:'wt-go','aria-label':'Смотреть '+c.name+' на ТВ',onclick:e=>{e.stopPropagation();swPlay({cid:c.id})}},ico('i-play')))})};
  fill()}

async function renderShow(b,d){
  header(d.title);
  const out=h('div',{class:'sw-wrap'});b.append(out);out.append(h('div',{class:'wt-msg',text:'Загружаю…'}));
  let r;try{r=await sg('show?id='+encodeURIComponent(d.id))}catch(e){if(cur()===d)out.replaceChildren(msgCard('error',render,'SWEET.TV'));return}
  if(cur()!==d)return;out.replaceChildren();
  const artOf=(o,fb='')=>(o&&(o.preview||o.banner||o.poster||o.image_url||o.thumb))||fb;
  const fmtMin=s=>s>=60?Math.round(s/60)+' мин':(s>0?s+' с':'');
  const heroArt=artOf(r);
  out.append(h('div',{class:'sw-hero'},
    heroArt?h('div',{class:'sw-hero-img',style:'background-image:'+picture(heroArt)}):'',
    h('div',{class:'sw-hero-body'},h('h3',{text:r.title||d.title}),
      h('div',{class:'wt-acts'},swFavBtn('show:'+d.id,{title:r.title||d.title,thumb:heroArt},r.favourite)))));
  const seasons=Array.isArray(r.seasons)&&r.seasons.length?r.seasons:null;
  if(seasons){
    const nu=r.next_up||null;
    let sIdx=(nu&&typeof nu.season_index==='number'&&nu.season_index>=0&&nu.season_index<seasons.length)?nu.season_index:0;
    const sp=h('div',{class:'sw-pills'}),list=h('div',{class:'wt-list'});
    out.append(sp,list);
    const drawS=()=>{
      sp.replaceChildren(...seasons.map((s,i)=>h('button',{class:'sw-pill'+(i===sIdx?' on':''),text:s.title||('Сезон '+(s.number||i+1)),onclick:()=>{sIdx=i;drawS()}})));
      list.replaceChildren();
      lazy(list,seasons[sIdx].episodes||[],ep=>swRow({pic:artOf(ep,heroArt),title:ep.title||('Серия '+(ep.episode||ep.number||'')),
        subs:[fmtMin(ep.duration||0),ep.watched?'просмотрено':''].filter(Boolean),
        pct:ep.resume>0&&ep.duration>0?100*ep.resume/ep.duration:0,
        open:()=>swPlay(ep.movie_id?{movie_id:String(ep.movie_id),episode_id:ep.id,owner_id:ep.owner_id||0,start:ep.resume||0}:{cid:ep.cid,epg:ep.epg,at:ep.resume>0?'resume':'start'})}))};
    drawS();return}
  const eps=r.episodes||[];
  if(!eps.length){out.append(msgCard('empty'));return}
  const list=h('div',{class:'wt-list'});out.append(list);
  lazy(list,eps,e=>swRow({pic:artOf(e),title:e.episode>0?'Серия '+e.episode+(e.title?' · '+e.title:''):e.title||'Серия',
    subs:[e.channel_name||e.channel,e.when||(e.start?dayTime(e.start):''),e.watched?'просмотрено':''].filter(Boolean),
    pct:e.resume>0&&e.stop>e.start?100*e.resume/(e.stop-e.start):0,dim:e.available===false,
    open:e.available!==false?()=>swSheet(d.title,e.title||'',(e.resume>0?[['Продолжить с '+tm(e.resume),{cid:e.cid,epg:e.epg,at:'resume'}]]:[]).concat([['Смотреть с начала',{cid:e.cid,epg:e.epg,at:'start'}]])):null}))}

async function renderVod(b,d){
  header(d.title);
  const out=h('div',{class:'sw-wrap'});b.append(out);out.append(h('div',{class:'wt-msg',text:'Загружаю…'}));
  let r;try{r=await sg('vod?id='+encodeURIComponent(d.id))}catch(e){if(cur()===d)out.replaceChildren(msgCard('error',render,'SWEET.TV'));return}
  if(cur()!==d)return;out.replaceChildren();
  const artOf=(o,fb='')=>(o&&(o.preview||o.banner||o.poster||o.image_url||o.thumb))||fb;
  const fmtMin=s=>s>=60?Math.round(s/60)+' мин':(s>0?s+' с':'');
  const mid=String(r.movie_id||String(r.id||'').replace(/^vod:/,''));
  const heroArt=artOf(r);
  const seasons=r.seasons||[];
  const durMeta=seasons.length?seasons.length+' сез.':fmtMin(r.duration||0);
  const meta=[r.imdb?'IMDb '+r.imdb:'',r.year,durMeta].filter(Boolean).join(' · ');
  const nu=seasons.length?(r.next_up||null):null;
  const acts=h('div',{class:'wt-acts'});
  if(nu){
    const nuLbl=nu.mode==='resume'?'Продолжить С'+nu.season_number+' Э'+nu.episode_number+' с '+tm(nu.resume):('Смотреть С'+(nu.season_number||1)+' Э'+(nu.episode_number||1));
    acts.append(h('button',{class:'wt-btn pri',text:nuLbl,onclick:()=>swPlay({movie_id:mid,episode_id:nu.episode_id,owner_id:nu.owner_id||r.owner_id||0,start:nu.mode==='resume'?nu.resume:0})}));
  }else{
    if(r.resume>0)acts.append(h('button',{class:'wt-btn pri',text:'Продолжить с '+tm(r.resume),onclick:()=>swPlay({movie_id:mid,owner_id:r.owner_id||0,start:r.resume})}));
    acts.append(h('button',{class:'wt-btn'+(r.resume>0?'':' pri'),text:r.resume>0?'С начала':'Смотреть',onclick:()=>swPlay({movie_id:mid,owner_id:r.owner_id||0,start:0})}));
  }
  acts.append(swFavBtn('vod:'+mid,{title:r.title||d.title,thumb:heroArt},r.favourite));
  out.append(h('div',{class:'sw-hero'},
    heroArt?h('div',{class:'sw-hero-img',style:'background-image:'+picture(heroArt)}):'',
    h('div',{class:'sw-hero-body'},h('h3',{text:r.title||d.title}),
      meta?h('div',{class:'sw-meta',text:meta}):'',
      r.description?h('div',{class:'sw-desc',text:r.description}):'',acts)));
  if(seasons.length){
    let sIdx=(nu&&typeof nu.season_index==='number'&&nu.season_index>=0&&nu.season_index<seasons.length)?nu.season_index:0;
    const sp=h('div',{class:'sw-pills'}),list=h('div',{class:'wt-list'});
    out.append(sp,list);
    const drawS=()=>{
      sp.replaceChildren(...seasons.map((s,i)=>h('button',{class:'sw-pill'+(i===sIdx?' on':''),text:s.title||('Сезон '+(s.number||i+1)),onclick:()=>{sIdx=i;drawS()}})));
      list.replaceChildren();
      lazy(list,seasons[sIdx].episodes||[],ep=>swRow({pic:artOf(ep),title:ep.title||('Серия '+(ep.number||'')),
        subs:[fmtMin(ep.duration||0),ep.resume>0?'с '+tm(ep.resume):'',ep.watched?'просмотрено':''].filter(Boolean),
        pct:ep.resume>0&&ep.duration>0?100*ep.resume/ep.duration:0,
        open:()=>swPlay({movie_id:mid,episode_id:ep.id,owner_id:ep.owner_id||r.owner_id||0,start:ep.resume||0})}))};
    drawS();
  }}

async function renderGuide(b,d){
  header(d.title);
  const out=h('div',{class:'sw-wrap'});b.append(out);out.append(h('div',{class:'wt-msg',text:'Загружаю…'}));
  let r;try{r=await sg('guide?cid='+encodeURIComponent(d.cid))}catch(e){if(cur()===d)out.replaceChildren(msgCard('error',render,'SWEET.TV'));return}
  if(cur()!==d)return;out.replaceChildren();
  const cu=r.current,now=r.now||Date.now()/1000,cid=r.cid||d.cid,card=h('div',{class:'wt-card'},h('div',{class:'wt-sub',text:'Сейчас'}));
  if(cu){
    const pct=cu.stop>cu.start?Math.max(0,Math.min(100,100*(now-cu.start)/(cu.stop-cu.start))):0;
    card.append(h('b',{class:'wt-gt',text:cu.title||'Без названия'}),h('div',{class:'wt-sub',text:hm(cu.start)+'–'+hm(cu.stop)}),
      h('div',{class:'wt-bar'},h('i',{style:'width:'+pct+'%'})));
  }else card.append(h('div',{class:'wt-gt',text:'Нет программы'}));
  const acts=h('div',{class:'wt-acts'},h('button',{class:'wt-btn pri',text:'Смотреть эфир',onclick:()=>swPlay({cid})}));
  if(cu&&cu.archive)acts.append(h('button',{class:'wt-btn',text:'С начала',onclick:()=>swPlay({cid,epg:cu.id,from_start:true})}));
  if(cu&&cu.resume>0)acts.append(h('button',{class:'wt-btn',text:'Продолжить с '+tm(cu.resume),onclick:()=>swPlay({cid,epg:cu.id,at:'resume'})}));
  card.append(acts);
  if(!r.archive)card.append(h('div',{class:'wt-note',text:'У этого канала нет архива'}));
  out.append(card);
  // 7-day date pills
  const daysRow=h('div',{class:'sw-days'}),dayList=h('div',{class:'wt-list'});
  const dayDates=[];
  for(let k=-6;k<=1;k++){
    const dt=new Date((now+k*86400)*1000);
    const iso=dt.getFullYear()+'-'+String(dt.getMonth()+1).padStart(2,'0')+'-'+String(dt.getDate()).padStart(2,'0');
    const lbl=k===0?'Сегодня':k===-1?'Вчера':k===1?'Завтра':dt.toLocaleDateString('ru',{weekday:'short',day:'numeric',month:'short'});
    dayDates.push({k,iso,lbl});
  }
  let selDay='local';
  const showLocal=()=>{
    dayList.replaceChildren();
    const past=r.past||[],next=r.next||[];
    if(past.length){
      dayList.append(h('h3',{class:'wt-h',text:'Ранее'}));
      lazy(dayList,past,e=>swRow({title:e.title,subs:[dayTime(e.start)+(e.watched?' · просмотрено':''),e.archive?'':'Нет в архиве'],
        pct:e.resume>0&&e.stop>e.start?100*e.resume/(e.stop-e.start):0,dim:!e.archive,
        open:e.archive?()=>swSheet(e.title,dayTime(e.start)+'–'+hm(e.stop),
          (e.resume>0?[['Продолжить с '+tm(e.resume),{cid,epg:e.id,at:'resume'}]]:[]).concat([['Смотреть с начала',{cid,epg:e.id,at:'start'}]])):null}))}
    if(next.length){
      dayList.append(h('h3',{class:'wt-h',text:'Далее'}));
      next.slice(0,25).forEach(e=>dayList.append(h('div',{class:'wt-upr'},h('time',{text:hm(e.start)}),h('span',{text:e.title||'Без названия'}))))}
  };
  const loadDay=async iso=>{
    selDay=iso;drawDays();dayList.replaceChildren(h('div',{class:'wt-msg',text:'Загружаю…'}));
    try{const dr=await sg('day?cid='+encodeURIComponent(cid)+'&date='+encodeURIComponent(iso));if(cur()!==d||selDay!==iso)return;
      dayList.replaceChildren();
      const items=dr.items||[];if(!items.length){dayList.append(msgCard('empty'));return}
      lazy(dayList,items,e=>swRow({title:e.title,subs:[hm(e.start)+'–'+hm(e.stop),e.watched?'просмотрено':''],
        pct:e.resume>0&&e.stop>e.start?100*e.resume/(e.stop-e.start):0,dim:!e.archive,
        open:e.archive?()=>swSheet(e.title,hm(e.start)+'–'+hm(e.stop),
          (e.resume>0?[['Продолжить с '+tm(e.resume),{cid,epg:e.epg||e.id,at:'resume'}]]:[]).concat([['Смотреть с начала',{cid,epg:e.epg||e.id,at:'start'}]])):null}))}
    catch(e){if(cur()===d)dayList.replaceChildren(msgCard('error',()=>loadDay(iso),'SWEET.TV'))}};
  const drawDays=()=>{
    daysRow.replaceChildren(...dayDates.map(dd=>h('button',{class:'sw-pill'+((selDay===dd.iso||(selDay==='local'&&dd.k===0))?' on':''),text:dd.lbl,
      onclick:()=>loadDay(dd.iso)})))};
  out.append(daysRow,dayList);drawDays();showLocal();
}
"""
