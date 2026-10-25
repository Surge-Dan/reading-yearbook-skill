/* Offline reading yearbook. Charts adapted from lieflat-charts Basics B2/F2,
 * B1/F1 Rung Bars and C1/F5 Tick Rows, including draw / pop / fade animation;
 * PolyForm Noncommercial 1.0.0, full license retained in this document. */
(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('reading-data').textContent);
  const art = JSON.parse(document.getElementById('reading-art').textContent);
  const $ = s => document.querySelector(s), $$ = s => [...document.querySelectorAll(s)];
  $$('[data-art]').forEach(image=>{image.src=art[image.dataset.art];});
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const serif = 'ReadingSerif, "Noto Serif SC", "SimSun", serif';
  const state = {query:'', status:'all', category:'', list:false, expanded:false, quote:0, busy:false, preview:'cover', ratio:'3:4', undo:[], selection:new Set(), composing:false};
  const bookMap = new Map(data.books.map(b => [b.book_id,b]));
  const highlights = data.books.flatMap(b => b.highlights.map(n => ({...n,book:b})));
  const thoughts = data.books.flatMap(b => b.thoughts.map(n => ({...n,book:b})));
  const readingEntries = highlights.length ? highlights : thoughts;
  const entryKind = highlights.length ? 'highlight' : 'thought';
  let quoteBook='';
  const collection=data.collection_status;
  if(collection && (!collection.complete || collection.errors?.length)){
    $('#collectionNotice').hidden=false;
    $('#collectionMessage').textContent=collection.message || '部分材料暂未获取。已取得的记录仍可浏览和导出；请让助手重新同步缺失材料。';
  }
  function enhanceSelect(select){
    const box=document.createElement('div');box.className='paper-select';
    select.parentNode.insertBefore(box,select);box.append(select);select.hidden=true;select.tabIndex=-1;
    const trigger=document.createElement('button');trigger.type='button';trigger.className='select-trigger';
    trigger.id=select.id+'Trigger';trigger.setAttribute('aria-haspopup','listbox');trigger.setAttribute('aria-expanded','false');
    trigger.setAttribute('aria-label',select.getAttribute('aria-label')||'选择图片比例');
    const list=document.createElement('div');list.id=select.id+'Options';list.className='select-menu';list.hidden=true;
    list.setAttribute('role','listbox');list.setAttribute('aria-label',trigger.getAttribute('aria-label'));
    trigger.setAttribute('aria-controls',list.id);box.append(trigger,list);
    let active=0;
    function close(restore=false){list.hidden=true;trigger.setAttribute('aria-expanded','false');if(restore)trigger.focus({preventScroll:true});}
    function sync(){
      trigger.innerHTML=`<span>${esc(select.selectedOptions[0]?.textContent||'请选择')}</span><svg viewBox="0 0 20 20" aria-hidden="true"><path d="m5 8 5 5 5-5"/></svg>`;
      list.innerHTML=[...select.options].map((o,i)=>`<button type="button" role="option" tabindex="-1" aria-selected="${o.selected}" data-option="${i}"><span>${esc(o.textContent)}</span><span class="option-check" aria-hidden="true">${o.selected?'✓':''}</span></button>`).join('');
      [...list.children].forEach((b,i)=>b.onclick=()=>{select.selectedIndex=i;select.dispatchEvent(new Event('change',{bubbles:true}));close(true);});
      trigger.disabled=select.disabled;
    }
    function focusOption(i){const items=[...list.children];active=Math.max(0,Math.min(i,items.length-1));items[active]?.focus({preventScroll:true});items[active]?.scrollIntoView({block:'nearest'});}
    function open(i=select.selectedIndex){
      if(trigger.disabled||select.disabled)return;list.hidden=false;trigger.setAttribute('aria-expanded','true');
      const rect=trigger.getBoundingClientRect(),below=innerHeight-rect.bottom-12,above=rect.top-12;
      const upwards=below<180&&above>below;box.classList.toggle('opens-up',upwards);
      list.style.maxHeight=Math.max(60,Math.min(300,(upwards?above:below)-8))+'px';focusOption(i);
    }
    trigger.onclick=()=>list.hidden?open():close();
    trigger.onkeydown=e=>{if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();open(e.key==='Home'?0:e.key==='End'?select.options.length-1:select.selectedIndex);}};
    list.onkeydown=e=>{
      if(['ArrowDown','ArrowUp','Home','End'].includes(e.key)){e.preventDefault();focusOption(e.key==='Home'?0:e.key==='End'?list.children.length-1:active+(e.key==='ArrowDown'?1:-1));}
      else if(e.key==='Escape'){e.preventDefault();e.stopPropagation();close(true);}
      else if(e.key==='Tab')close(true);
    };
    document.addEventListener('click',e=>{if(!box.contains(e.target))close();});
    box.addEventListener('focusout',e=>{if(!box.contains(e.relatedTarget))close();});
    addEventListener('resize',()=>close());
    new MutationObserver(()=>{trigger.disabled=select.disabled;if(select.disabled)close();}).observe(select,{attributes:true,attributeFilter:['disabled']});
    select.addEventListener('change',sync);sync();return {sync,close};
  }
  let toastTimer, searchTimer, previousFocus, originalHash='', dialogPushed=false, renderToken=0;
  const hours = v => v == null ? '未记录' : `${(v/3600).toFixed(1)}小时`;
  const duration = v => v == null ? '未记录' : `${Math.floor(v/3600)}小时${Math.floor(v%3600/60)}分钟`;
  const value = v => v == null ? '—' : String(v);
  const statusLabel = b => ({finished:'已读完',reading:'在读',unknown:'状态未记录'}[b.status]);
  const scope = data.coverage.complete ? `全年${data.books.length}本` : `已载入${data.books.length}本 · 年度记录${value(data.coverage.annual_books)}本`;
  function updateNavSurface(){document.querySelector('.masthead').classList.toggle('is-scrolled',scrollY>8);}
  addEventListener('scroll',updateNavSurface,{passive:true});updateNavSurface();
  function toast(text) {$('#toast').textContent=text;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,2800);}
  $('#period').textContent = String(data.year);
  $('#modeNotice').textContent = data.source_mode==='sample' ? '示例数据 · 不代表真实阅读记录' : data.verification_status!=='live_verified' ? '数据尚未核验，供预览使用' : '';
  const time = data.summary.seconds;
  $('#stats').innerHTML = `<div class="metric lead"><strong>${time==null?'—':`${Math.floor(time/3600)}<em>小时</em>${Math.floor(time%3600/60)}<em>分钟</em>`}</strong><span>累计阅读时长</span></div>` + [[data.summary.read,'本读过'],[data.summary.finished,'本读完'],[data.summary.read_days,'天阅读'],[data.summary.notes,'条笔记']].map(([v,t])=>`<div class="metric"><strong>${esc(value(v))}</strong><span>${t}</span></div>`).join('');
  $('#distributionScope').textContent=`${scope} · 按主分类计数`;
  $('#shelfScope').textContent=scope;

  // lieflat's obsReveal, adapted to independent replay controls and persistent
  // DOM interactions. No timers accumulate when resizing, filtering or replaying.
  const motionMedia=matchMedia('(prefers-reduced-motion:reduce)'), chartMotion=new Map();
  const rnd=(i,k)=>Math.abs(((i*73856093)^(k*19349663))%1000)/1000;
  function settleChart(record){record.version++;record.node.getAnimations({subtree:true}).forEach(a=>a.cancel());record.node.classList.remove('is-playing');record.node.dataset.motionState='complete';}
  function playChart(record){
    settleChart(record);record.seen=true;
    if(motionMedia.matches||matchMedia('print').matches)return;
    void record.node.offsetWidth;record.node.classList.add('is-playing');record.node.dataset.motionState='playing';
    const version=++record.version, animations=record.node.getAnimations({subtree:true});
    Promise.allSettled(animations.map(a=>a.finished)).then(()=>{if(record.version===version){record.node.classList.remove('is-playing');record.node.dataset.motionState='complete';}});
  }
  function revealChart(id){
    let record=chartMotion.get(id);
    if(!record){record={node:$('#'+id),seen:false,version:0};chartMotion.set(id,record);
      if('IntersectionObserver' in window){record.observer=new IntersectionObserver(entries=>{if(entries.some(e=>e.isIntersecting)){record.observer.disconnect();playChart(record);}},{threshold:.2});record.observer.observe(record.node);}else playChart(record);
    }else if(record.seen)settleChart(record);
  }
  $$('[data-replay]').forEach(b=>b.onclick=()=>{const record=chartMotion.get(b.dataset.replay);if(record){record.observer?.disconnect();playChart(record);}});
  motionMedia.addEventListener('change',()=>{if(motionMedia.matches)chartMotion.forEach(settleChart);});
  addEventListener('beforeprint',()=>chartMotion.forEach(settleChart));

  function drawChart() {
    if(chartMotion.has('chart'))settleChart(chartMotion.get('chart'));
    const end = data.summary.complete_months;
    const months = data.summary.monthly.slice(0,end);
    $('#monthlyTable').innerHTML='<table><thead><tr><th>月份</th><th>时长</th></tr></thead><tbody>'+months.map((v,i)=>`<tr><td>${i+1}月</td><td>${esc(duration(v))}</td></tr>`).join('')+'</tbody></table>';
    if (!months.some(x=>x!=null)) {$('#chart').innerHTML='<p class="empty">暂无完整月份的阅读时长</p>';return;}
    // B2 skeleton: calendar floor, hairline path, individual dots, peak label.
    // Mapping uses unrounded seconds; null breaks a path, a measured zero stays on baseline.
    const mobile=matchMedia('(max-width:520px)').matches, W=Math.max(280,$('#chart').clientWidth),H=mobile?220:235;
    const left=37,right=W-15,base=H-37,max=Math.max(...months.filter(v=>v!=null).map(v=>v/3600),1);
    const top=Math.ceil(max/2)*2, x=i=>months.length===1?(left+right)/2:left+i*(right-left)/(months.length-1), y=v=>base-(v/3600)/top*(base-25);
    let svg=`<svg viewBox="0 0 ${W} ${H}" role="group" aria-label="月度阅读时长，单位小时"><title>月度阅读时长</title>`;
    for (const tick of [0,top/2,top]) svg+=`<line x1="${left}" y1="${base-tick/top*(base-25)}" x2="${right}" y2="${base-tick/top*(base-25)}" stroke="#d5d3ca" stroke-width=".7" ${tick?'stroke-dasharray="2 4"':''}/><text x="${left-12}" y="${base-tick/top*(base-25)+4}" text-anchor="end" fill="#696962" font-size="12">${tick}</text>`;
    svg+='<text x="0" y="13" fill="#696962" font-size="11">小时</text>';
    let segment=[]; const paths=[];
    months.forEach((v,i)=>{if(v==null){if(segment.length)paths.push(segment);segment=[];}else segment.push([x(i),y(v)]);});if(segment.length)paths.push(segment);
    paths.forEach(points=>svg+=`<path d="${points.map((p,i)=>(i?'L':'M')+p.join(' ')).join(' ')}" fill="none" stroke="#b94035" stroke-width="1.4" pathLength="1" class="draw"/>`);
    const peak=months.findIndex(v=>v!=null&&v===Math.max(...months.filter(v=>v!=null)));
    months.forEach((v,i)=>{svg+=`<line x1="${x(i)}" y1="${base}" x2="${x(i)}" y2="${base-7}" stroke="#bdbab0" stroke-width=".8"/><text x="${x(i)}" y="${base+24}" text-anchor="middle" fill="#696962" font-size="12">${i+1}月</text>`;
      if(v!=null) {svg+=`<circle data-chart-month="${i}" tabindex="0" role="button" aria-label="${i+1}月，${esc(duration(v))}" cx="${x(i)}" cy="${y(v)}" r="${i===peak?4.5:3}" fill="#b94035" class="pop" style="animation-delay:${.2+i*.03}s"/><circle cx="${x(i)}" cy="${y(v)}" r="11" fill="transparent" data-chart-month="${i}" aria-hidden="true"/>`;
        svg+=`<text x="${x(i)}" y="${y(v)-13}" text-anchor="middle" fill="${i===peak?'#b94035':'#68665e'}" font-size="11" class="fade" style="paint-order:stroke;stroke:#faf6e9;stroke-width:4;animation-delay:${1+i*.01}s">${(v/3600).toFixed(1)}</text>`;}
    }); $('#chart').innerHTML=svg+'</svg>';
    $$('[data-chart-month]').forEach(el=>{const show=()=>$('#chartReadout').textContent=`${Number(el.dataset.chartMonth)+1}月 · ${duration(months[el.dataset.chartMonth])}`;el.addEventListener('mouseenter',show);el.addEventListener('focus',show);el.addEventListener('click',show);el.addEventListener('keydown',e=>{if(e.key==='Enter'||e.key===' '){e.preventDefault();show();}});});
    revealChart('chart');
  }
  drawChart(); let resizeFrame;addEventListener('resize',()=>{cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(drawChart);});

  const categories = [...new Set(data.books.map(b=>b.category))];
  const categoryPalette=['#bd5143','#4477a1','#b8973b','#5c897c','#ac7b84','#897b9e','#71828b'];
  const categoryCounts = categories.map(c=>({name:c,count:data.books.filter(b=>b.category===c).length})).sort((a,b)=>b.count-a.count);
  const maxCount=Math.max(...categoryCounts.map(c=>c.count),1),spineUnit=Math.max(1,Math.ceil(maxCount/10));
  $('#distributionLegend').textContent=spineUnit===1?'一块书脊，一本书':'每块书脊代表 '+spineUnit+' 本，末块按实际数量绘制';
  $('#distribution').innerHTML=categoryCounts.length?'<div class="distribution-grid">'+categoryCounts.map((c,i)=>{
    const stackHeight=Math.ceil(c.count/spineUnit)*17+12;
    let marks='';for(let k=0;k<Math.ceil(c.count/spineUnit);k++){const value=Math.min(spineUnit,c.count-k*spineUnit),h=13*value/spineUnit,x=12+[0,2,-1][k%3],y=stackHeight-7-k*17-h;
      marks+=`<g data-spine-value="${value}" class="fade" style="animation-delay:${i*.06+k*.025}s"><rect x="${x+1}" y="${y+2}" width="78" height="${h}" rx="2" fill="#403527" opacity=".10"/><rect x="${x}" y="${y}" width="78" height="${h}" rx="2" fill="${categoryPalette[i%7]}"/><rect x="${x+57}" y="${y+1}" width="17" height="${Math.max(0,h-2)}" rx="1" fill="#f7f2e5" opacity=".75"/><path d="M${x+8} ${y+2}v${Math.max(0,h-4)}" stroke="#fff" opacity=".4"/></g>`;
    }
    const percent=Math.round(c.count/data.books.length*100);
    return `<button class="category-rung category-stack" data-category="${esc(c.name)}" aria-pressed="false" aria-label="${esc(c.name)}，${c.count}本，占${percent}%，筛选书架"><svg viewBox="0 0 104 ${stackHeight}" style="height:${stackHeight}px" aria-hidden="true">${marks}</svg><span class="category-name">${esc(c.name)}</span><span class="category-amount"><strong class="category-count">${c.count}</strong><span>本 · ${percent}%</span></span></button>`;
  }).join('')+'</div>':'<p class="empty">暂无可统计书目</p>';
  revealChart('distribution');
  $$('[data-category]').forEach(button=>button.onclick=()=>{state.category=state.category===button.dataset.category?'':button.dataset.category;drawBooks();$('#shelf').scrollIntoView({block:'start'});});
  const timedBooks=data.books.filter(b=>b.reading_seconds!=null).sort((a,b)=>b.reading_seconds-a.reading_seconds);
  const maxSeconds=Math.max(...timedBooks.map(b=>b.reading_seconds),1);
  $('#investmentScope').textContent=timedBooks.length?`已记录时长的${timedBooks.length}本 · 横条按实际时长同比例显示`:'暂未载入逐书阅读时长';
  $('#investment').innerHTML=timedBooks.length?timedBooks.map((b,i)=>{
    const color=categoryPalette[categoryCounts.findIndex(c=>c.name===b.category)%7],width=b.reading_seconds/maxSeconds*480;
    return `<button class="tick-row investment-row" data-open-book="${esc(b.book_id)}" data-seconds="${b.reading_seconds}" aria-label="${esc(b.title)}，${esc(duration(b.reading_seconds))}，查看详情"><span class="investment-cover" aria-hidden="true"><span>书</span>${b.cover?`<img src="${esc(b.cover)}" alt="" loading="lazy">`:''}</span><span class="tick-label">${esc(b.title)}</span><svg viewBox="0 0 480 28" aria-hidden="true"><rect y="8" width="480" height="12" rx="3" fill="#e9e1cf"/><path d="M120 6v16M240 6v16M360 6v16" stroke="#c9c4b3" stroke-width=".6"/><rect class="duration-fill fade" style="animation-delay:${i*.045}s" y="8" width="${width}" height="12" rx="3" fill="${color}"/></svg><span class="tick-time">${esc(duration(b.reading_seconds))}</span></button>`;
  }).join(''):'<p class="empty">有逐书数据时，这里会呈现每本书的阅读投入。</p>';
  $$('.investment-cover img').forEach(img=>img.addEventListener('error',()=>{img.hidden=true;}));
  $('#investmentTable').innerHTML='<table><thead><tr><th>书名</th><th>时长</th><th>秒数</th></tr></thead><tbody>'+timedBooks.map(b=>`<tr><td>${esc(b.title)}</td><td>${esc(duration(b.reading_seconds))}</td><td>${b.reading_seconds}</td></tr>`).join('')+'</tbody></table>';
  revealChart('investment');
  const events=[]; const seenEvents=new Set();
  data.books.forEach(b=>{for(const [type,list] of [['划线',b.highlights],['笔记',b.thoughts]])list.forEach(n=>{if(n.created_at&&Number(n.created_at.slice(0,4))===data.year){const key=`${b.book_id}|${type}|${n.source_id||n.text+'|'+n.created_at}`;if(!seenEvents.has(key)){seenEvents.add(key);events.push({date:n.created_at,type,book:b,text:n.text});}}});
    for(const [type,date] of [['开始阅读',b.start_date],['读完',b.finish_date]])if(date&&Number(date.slice(0,4))===data.year)events.push({date,type,book:b});});
  events.sort((a,b)=>a.date.localeCompare(b.date));
  const eventHtml = e=>`<div class="timeline-row"><time datetime="${esc(e.date)}">${e.date.slice(5).replace('-','.')}</time><button class="timeline-book" data-open-book="${esc(e.book.book_id)}">${esc(e.book.title)}</button><span class="event-type">${e.type}</span></div>`;
  const groups=[...new Set(events.map(e=>e.date.slice(0,7)))];
  const previewEvents=[],previewBooks=new Set();
  for(const e of [...events].reverse())if(!previewBooks.has(e.book.book_id)&&previewEvents.length<4){previewBooks.add(e.book.book_id);previewEvents.push(e);}
  previewEvents.sort((a,b)=>a.date.localeCompare(b.date));
  const remainingEvents=events.filter(e=>!previewEvents.includes(e));
  $('#timeline').innerHTML=events.length?previewEvents.map(eventHtml).join('')+(remainingEvents.length?`<details><summary>展开其余${remainingEvents.length}条记录</summary>${groups.map(m=>{const rows=remainingEvents.filter(e=>e.date.startsWith(m));return rows.length?`<h3 class="timeline-month">${Number(m.slice(5))}月</h3>${rows.map(eventHtml).join('')}`:'';}).join('')}</details>`:''):'<p class="empty">暂无带日期的阅读记录</p>';

  function fallbackCover(b){return `<span class="cover-fallback"><span>${esc(b.title)}</span><small>${esc(b.author)}</small></span>`;}
  function coverMarkup(b) {return b.cover?`<img data-cover-book="${esc(b.book_id)}" src="${esc(b.cover)}" alt="《${esc(b.title)}》书封" loading="lazy">`:fallbackCover(b);}
  document.addEventListener('error',e=>{if(e.target instanceof HTMLImageElement&&e.target.dataset.coverBook){const b=bookMap.get(e.target.dataset.coverBook);if(b){const holder=document.createElement('span');holder.innerHTML=fallbackCover(b);e.target.replaceWith(holder.firstElementChild);}}},true);
  function visibleBooks(){const q=state.query.toLocaleLowerCase();return data.books.filter(b=>(state.status==='all'||b.status===state.status)&&(!state.category||b.category===state.category)&&(!q||(b.title+' '+b.author).toLocaleLowerCase().includes(q)));}
  function drawBooks(printing=false) {
    const all=visibleBooks(), filtered=!!state.query||!!state.category||state.status!=='all', collapsed=!printing&&!filtered&&!state.expanded&&all.length>4;
    const picked=all.filter(b=>b.selected), rows=collapsed?(picked.length?picked:all).slice(0,4):all;
    $('#expandShelf').hidden=filtered||printing||all.length<=4;$('#expandShelf').setAttribute('aria-expanded',String(state.expanded));$('#expandShelf').textContent=state.expanded?'收起书目 ↑':`展开全部${all.length}本 →`;
    $('#books').classList.toggle('list',state.list);
    $('#books').innerHTML=rows.length?rows.map(b=>`<article class="book-entry"><button class="book" data-open-book="${esc(b.book_id)}"><span class="cover-wrap">${coverMarkup(b)}</span><h3>${esc(b.title)}</h3><p class="author">${esc(b.author)}</p><p class="book-meta">${esc(statusLabel(b))}${b.progress==null?'':` · ${b.progress}%`}</p></button><div class="book-actions"><button class="text-button" data-open-book="${esc(b.book_id)}">阅读详情 ↗</button><button class="text-button" data-share-book="${esc(b.book_id)}">预览分享卡</button></div></article>`).join(''):`<p class="empty">${data.books.length?'没有找到对应的书。可以换个关键词，或清除筛选。':data.coverage.complete?'这一年还没有阅读记录。以后读过的书，可以重新同步到这里。':'暂未取得这一年的书目，请检查数据来源或让助手重新同步。'}</p>`;
    $('#resultCount').textContent=`${collapsed?'精选':'显示'}${rows.length}／${data.books.length}本${state.category?' · '+state.category:''}`;
    $('#clearFilters').hidden=!state.query&&!state.category&&state.status==='all';
    $$('[data-status]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.status===state.status)));
    $$('[data-category]').forEach(b=>b.setAttribute('aria-pressed',String(b.dataset.category===state.category)));
  }
  drawBooks();
  if(!data.books.length){$('.shelf-tools').hidden=true;$('.filter-summary').hidden=true;}
  $('#expandShelf').onclick=()=>{state.expanded=!state.expanded;drawBooks();};
  $$('[data-status]').forEach(b=>b.onclick=()=>{state.status=b.dataset.status;drawBooks();});
  $('#clearFilters').onclick=()=>{clearTimeout(searchTimer);state.query='';state.status='all';state.category='';$('#search').value='';drawBooks();};
  const updateSearch=()=>{state.query=$('#search').value.trim();drawBooks();};
  $('#search').addEventListener('compositionstart',()=>{state.composing=true;clearTimeout(searchTimer);});
  $('#search').addEventListener('compositionend',()=>{state.composing=false;updateSearch();});
  $('#search').addEventListener('input',e=>{if(state.composing||e.isComposing)return;clearTimeout(searchTimer);searchTimer=setTimeout(updateSearch,180);});
  $('#viewSwitch').onclick=()=>{state.list=!state.list;$('#viewSwitch').setAttribute('aria-pressed',String(state.list));$('#viewSwitch').textContent=state.list?'封面视图':'列表视图';drawBooks();};

  function noteHtml(n,b,index,type){return `<div class="detail-note">${esc(n.text)}<small>${esc(n.created_at||'日期未记录')}${n.chapter_title?' · '+esc(n.chapter_title):n.chapter?' · 章节 '+esc(n.chapter):''}</small><button class="text-button" ${type==='划线'?'data-add-quote':'data-add-note'}="${esc(b.book_id)}" data-index="${index}">${type==='划线'?'用这句做分享卡':'用这条笔记做分享卡'}</button></div>`;}
  function emptyNotes(b,kind){return b.note_coverage?.[kind]==='complete'?(kind==='highlights'?'已核查：这本书没有划线记录。':'已核查：这本书没有个人想法或点评。'):(kind==='highlights'?'这本书尚未载入完整划线。':'这本书尚未载入完整个人笔记。');}
  function bookDetails(b,printing=false){
    const noteScope=b.note_coverage?.scope==='all_time'?'本书全部历史记录':'年内已载入记录';
    const section=(kind,title,rows)=>rows.length?`<section class="detail-section"><h3>${title} · ${rows.length}条</h3><p class="material-note">${noteScope}</p>${rows.map((n,i)=>printing?`<div class="detail-note">${esc(n.text)}<small>${esc(n.created_at||'日期未记录')}</small></div>`:noteHtml(n,b,i,kind==='highlights'?'划线':'笔记')).join('')}</section>`:'';
    const empty=['highlights','thoughts'].filter(k=>!b[k].length).map(k=>emptyNotes(b,k));
    return `<div class="detail-identity"><div>${coverMarkup(b)}</div><div><h2 ${printing?'':'id="detailTitle"'}>${esc(b.title)}</h2><p>${esc(b.author)}</p><p>${esc(statusLabel(b))} · ${esc(b.category)}${b.reading_seconds==null?'':' · 年内'+duration(b.reading_seconds)}</p></div></div>${b.intro?`<details class="detail-section" ${printing?'open':''}><summary>书籍简介</summary><p>${esc(b.intro)}</p></details>`:''}${section('highlights','划线',b.highlights)}${section('thoughts','我的笔记',b.thoughts)}${empty.length?`<div class="material-empty"><p>${empty.map(esc).join('<br>')}</p>${empty.length===2&&b.note_coverage?.highlights==='complete'&&b.note_coverage?.thoughts==='complete'?'<p>阅读本身也值得留下，书封与阅读信息仍可导出。</p>':''}</div>`:''}`;
  }
  function openBook(id,fromHash=false) {
    const b=bookMap.get(id);if(!b)return;
    if(!$('#detail').open){previousFocus=document.activeElement;originalHash=location.hash;}
    $('#detailContent').innerHTML=bookDetails(b);
    if(!$('#detail').open)$('#detail').showModal();$('#detail').scrollTop=0;
    if(!fromHash){history.pushState(null,'','#book='+encodeURIComponent(id));dialogPushed=true;}
  }
  function closeBook(){if(!$('#detail').open)return;$('#detail').close();if(dialogPushed&&location.hash.startsWith('#book=')){history.back();}else if(location.hash.startsWith('#book=')){history.replaceState(null,'',originalHash.startsWith('#book=')?'#shelf':originalHash||'#shelf');}dialogPushed=false;previousFocus?.isConnected&&previousFocus.focus({preventScroll:true});}
  $('#detail .close').onclick=closeBook;
  $('#detail').addEventListener('cancel',e=>{e.preventDefault();closeBook();});
  addEventListener('hashchange',()=>{if(location.hash.startsWith('#book=')){try{openBook(decodeURIComponent(location.hash.slice(6)),true);}catch{toast('书籍链接无效');}}else if($('#detail').open){$('#detail').close();dialogPushed=false;previousFocus?.isConnected&&previousFocus.focus({preventScroll:true});}});
  if(location.hash.startsWith('#book=')){try{openBook(decodeURIComponent(location.hash.slice(6)),true);}catch{}}
  document.addEventListener('click',e=>{const open=e.target.closest('[data-open-book]');if(open)openBook(open.dataset.openBook);const add=e.target.closest('[data-share-book]');if(add)addBookShare(add.dataset.shareBook);const quote=e.target.closest('[data-add-quote]');if(quote){const b=bookMap.get(quote.dataset.addQuote);addBookShare(b.book_id,b.highlights[Number(quote.dataset.index)]?.text);toast('已加入分享，可在分享区预览');}const note=e.target.closest('[data-add-note]');if(note){const b=bookMap.get(note.dataset.addNote);addBookShare(b.book_id,b.thoughts[Number(note.dataset.index)]?.text,'thought');}});
  $('#sourcesDialog .close').onclick=()=>$('#sourcesDialog').close();
  $('#openSources').onclick=()=>{$('#sourcesContent').innerHTML=`<p>统计年份：${data.year}${data.as_of?'；采集日期：'+esc(data.as_of):''}</p><p>书目范围：${esc(scope)}。</p><p>模式：${esc(data.source_mode)}；核验状态：${esc(data.verification_status)}。</p><p>分布按已载入书籍的主分类计数；未知状态不归入“在读”。月度图只展示完整月份，缺失值不当作零。</p><p>时间线只展示本年有日期的事件。书籍简介、原文划线和个人笔记分别呈现。</p>${data.material_coverage?`<p>已核查${data.material_coverage.books_with_checked_highlights}本书的划线、${data.material_coverage.books_with_checked_thoughts}本书的个人想法。书籍详情保留本书全部历史记录，年度时间线只取${data.year}年。</p><p>年度汇总读完${value(data.summary.finished)}本；当前书架进度100%的书有${data.material_coverage.current_finished}本。年度汇总与当前阅读进度是不同口径；“已读完”筛选使用当前进度。进度采集日期：${esc(data.material_coverage.states_collected_on)}。</p>`:''}<p>字体优先使用本机Noto Serif SC／Noto Sans SC，无该字体时使用系统中文字体。文件不依赖在线字体或CDN。</p>`;$('#sourcesDialog').showModal();};

  async function copyText(text){try{if(navigator.clipboard?.writeText){await navigator.clipboard.writeText(text);}else{const t=document.createElement('textarea');t.value=text;document.body.append(t);t.select();if(!document.execCommand('copy'))throw Error('clipboard');t.remove();}toast('已复制');}catch{toast('复制失败，可选中文字后手动复制');}}
  $('#quoteBook').innerHTML='<option value="">全部书籍</option>'+data.books.filter(b=>entryKind==='highlight'?b.highlights.length:b.thoughts.length).map(b=>`<option value="${esc(b.book_id)}">${esc(b.title)}（${entryKind==='highlight'?b.highlights.length:b.thoughts.length}）</option>`).join('');
  $('#quoteBook').onchange=()=>{quoteBook=$('#quoteBook').value;state.quote=0;drawQuote();};
  const quoteSelector=enhanceSelect($('#quoteBook'));
  if(!highlights.length){$('#quotesTitle').textContent=thoughts.length?'随手记下的想法':'阅读也可以不留笔记';$('nav a[href="#quotes"]').textContent=thoughts.length?'个人笔记':'阅读记录';$('.quote-filter label').textContent='按书籍查看笔记';}
  function drawQuote(){const rows=quoteBook?readingEntries.filter(n=>n.book.book_id===quoteBook):readingEntries;
    $('.quote-filter').hidden=!readingEntries.length;$('.quote-pager').hidden=!readingEntries.length;
    if(!rows.length){
      const checked=data.books.length&&data.books.every(b=>b.note_coverage?.highlights==='complete'&&b.note_coverage?.thoughts==='complete');
      $('#quote').innerHTML=`<div class="material-empty"><p>${checked?'这一年的书里，还没有划线或个人笔记。':!data.books.length&&data.coverage.complete?'等有了阅读记录，这里会留下你划过的句子和随手写的想法。':'划线与个人笔记尚未完整取得，可让助手重新同步。'}</p><p>书架、阅读统计和书封分享都可以照常使用。</p></div>`;
      $('#quotePosition').textContent='0／0';$('#previousQuote').disabled=$('#nextQuote').disabled=true;return;
    }
    state.quote=Math.max(0,Math.min(state.quote,rows.length-1));
    const n=rows[state.quote];$('#quotePosition').textContent=`${state.quote+1}／${rows.length}`;
    $('#previousQuote').disabled=state.quote===0;$('#nextQuote').disabled=state.quote===rows.length-1;
    $('#quote').innerHTML=`<div class="quote-body"><blockquote>${esc(n.text)}</blockquote><p class="attribution">${entryKind==='thought'?'我的笔记 · ': '—'}《${esc(n.book.title)}》</p><p class="quote-scope">${n.book.note_coverage?.scope==='all_time'?'本书历史记录 · ':''}${esc(n.created_at||'日期未记录')}</p><div class="quote-actions"><button id="copyQuote" class="text-button">复制</button><button id="shareQuote" class="text-button">${entryKind==='thought'?'用这条笔记做分享卡':'用这句做分享卡'}</button></div></div>`;
    $('#copyQuote').onclick=()=>copyText(n.text);$('#shareQuote').onclick=()=>addBookShare(n.book.book_id,n.text,entryKind);
  }drawQuote();$('#previousQuote').onclick=()=>{state.quote--;drawQuote();};$('#nextQuote').onclick=()=>{state.quote++;drawQuote();};

  const pages=[{id:'cover',title:'封面',kind:'cover'},{id:'stats',title:'阅读统计',kind:'stats'},
    {id:'distribution',title:'阅读分布',kind:'distribution'},{id:'timeline',title:'阅读时间线',kind:'timeline'}];
  data.books.forEach(b=>pages.push({id:'book-'+b.book_id,title:b.title,kind:'book',book:b,quote:b.highlights[0]?.text||b.thoughts[0]?.text||'',textKind:b.highlights.length?'highlight':'thought'}));
  state.selection=new Set(pages.map(p=>p.id));
  let shareBookComposing=false;
  const bookShareBox=$('#bookSharePicker'),bookShareMenu=$('#bookShareMenu'),bookShareTrigger=$('#bookShareTrigger');
  function closeShareBooks(restore=false){bookShareMenu.hidden=true;bookShareTrigger.setAttribute('aria-expanded','false');if(restore)bookShareTrigger.focus({preventScroll:true});}
  function openShareBooks(){
    if(state.busy||bookShareTrigger.disabled)return;
    bookShareMenu.hidden=false;bookShareTrigger.setAttribute('aria-expanded','true');
    const rect=bookShareTrigger.getBoundingClientRect(),below=innerHeight-rect.bottom-12,above=rect.top-12,up=below<240&&above>below;
    bookShareBox.classList.toggle('opens-up',up);bookShareMenu.style.maxHeight=Math.max(100,Math.min(460,(up?above:below)-8))+'px';
    $('#shareBookSearch').focus({preventScroll:true});
  }
  function filterShareBooks(){
    const query=$('#shareBookSearch').value.trim().toLocaleLowerCase();let count=0;
    $$('#bookShareRows .share-page').forEach(row=>{const b=bookMap.get(row.dataset.bookId),match=!query||(b.title+' '+b.author).toLocaleLowerCase().includes(query);row.hidden=!match;if(match)count++;});
    $('#shareBookEmpty').hidden=count!==0;
  }
  bookShareTrigger.onclick=()=>bookShareMenu.hidden?openShareBooks():closeShareBooks();
  bookShareTrigger.onkeydown=e=>{if(e.key==='ArrowDown'){e.preventDefault();openShareBooks();}};
  bookShareMenu.addEventListener('keydown',e=>{if(e.key==='Escape'){e.preventDefault();e.stopPropagation();closeShareBooks(true);}});
  bookShareBox.addEventListener('focusout',e=>{if(!bookShareBox.contains(e.relatedTarget))closeShareBooks();});
  document.addEventListener('click',e=>{if(!bookShareBox.contains(e.target))closeShareBooks();});
  addEventListener('resize',()=>closeShareBooks());
  $('#shareBookSearch').addEventListener('compositionstart',()=>shareBookComposing=true);
  $('#shareBookSearch').addEventListener('compositionend',()=>{shareBookComposing=false;filterShareBooks();});
  $('#shareBookSearch').addEventListener('input',e=>{if(!shareBookComposing&&!e.isComposing)filterShareBooks();});
  function changeShareBooks(select){if(state.busy)return;recordUndo();for(const p of pages.filter(p=>p.kind==='book'))select?state.selection.add(p.id):state.selection.delete(p.id);drawShare();}
  $('#selectAllShareBooks').onclick=()=>changeShareBooks(true);$('#clearShareBooks').onclick=()=>changeShareBooks(false);$('#closeShareBooks').onclick=()=>closeShareBooks(true);
  function recordUndo(){state.undo.push({ids:[...state.selection],preview:state.preview,quotes:pages.filter(p=>p.kind==='book').map(p=>[p.id,p.quote,p.textKind])});if(state.undo.length>10)state.undo.shift();}
  function addBookShare(id,quote,kind='highlight'){if(state.busy){toast('导出中，请稍后再调整');return;}const b=bookMap.get(id);if(!b)return;recordUndo();let p=pages.find(p=>p.id==='book-'+id);if(!p){p={id:'book-'+id,title:b.title,kind:'book',book:b,quote:quote||b.highlights[0]?.text||b.thoughts[0]?.text||'',textKind:quote?kind:b.highlights.length?'highlight':'thought'};pages.push(p);}if(quote!==undefined){p.quote=quote;p.textKind=kind;}state.selection.add(p.id);state.preview=p.id;drawShare();toast('已加入分享');}
  function shareRow(p){return `<div class="share-page" ${p.kind==='book'?`data-book-id="${esc(p.book.book_id)}"`:''}><label><input type="checkbox" data-page="${esc(p.id)}"><span>${esc(p.title)}${p.kind==='book'?`<small>${esc(p.book.author)}</small>`:''}</span></label><button type="button" data-preview="${esc(p.id)}">预览</button></div>`;}
  function drawShare(){
    const books=pages.filter(p=>p.kind==='book');
    $('#sharePages').innerHTML=pages.filter(p=>p.kind!=='book').map(shareRow).join('');
    if($('#bookShareRows').dataset.count!==String(books.length)){$('#bookShareRows').innerHTML=books.map(shareRow).join('');$('#bookShareRows').dataset.count=String(books.length);}
    const selectedBooks=books.filter(p=>state.selection.has(p.id)).length;
    $('#bookShareLabel').textContent=books.length?`分享书籍 · 已选${selectedBooks}／${books.length}本`:'暂无可选书籍';
    $('#bookShareCount').textContent=`已选${selectedBooks}／${books.length}本`;
    bookShareTrigger.disabled=state.busy||!books.length;$('#selectAllShareBooks').disabled=state.busy;$('#clearShareBooks').disabled=state.busy;
    if(state.busy||!books.length)closeShareBooks();
    $('#selectedCount').textContent=`已选${state.selection.size}／${pages.length}页`;$('#undoSelection').disabled=!state.undo.length||state.busy;$('#exportGroup').disabled=!state.selection.size||state.busy;$('#exportOne').disabled=state.busy;
    $$('[data-page]').forEach(el=>{el.checked=state.selection.has(el.dataset.page);el.disabled=state.busy;el.onchange=()=>{if(state.busy)return;recordUndo();el.checked?state.selection.add(el.dataset.page):state.selection.delete(el.dataset.page);drawShare();};});
    $$('[data-preview]').forEach(el=>{el.disabled=state.busy;el.setAttribute('aria-pressed',String(state.preview===el.dataset.preview));el.onclick=()=>{if(state.busy)return;state.preview=el.dataset.preview;drawShare();};});
    filterShareBooks();updatePreview();
  }
  $('#undoSelection').onclick=()=>{const old=state.undo.pop();if(!old||state.busy)return;state.selection=new Set(old.ids);state.preview=old.preview;for(const [id,q,kind]of old.quotes){const p=pages.find(p=>p.id===id);if(p){p.quote=q;p.textKind=kind;}}drawShare();};
  $('#ratio').onchange=()=>{if(state.busy)return;state.ratio=$('#ratio').value;updatePreview();};
  function dimensions(ratio){return [900,ratio==='1:1'?900:ratio==='4:5'?1125:1200];}
  const images=new Map();
  function loadImage(src){if(!images.has(src))images.set(src,new Promise((resolve,reject)=>{const im=new Image();im.onload=()=>resolve(im);im.onerror=()=>reject(Error('书封加载失败'));im.src=src;}));return images.get(src);}
  const shareArtwork=window.ReadingShareArtwork.create({data,art,loadImage});
  async function canvasPage(p,ratio){return shareArtwork.render(p,ratio);}
  async function updatePreview(){const token=++renderToken,p=pages.find(p=>p.id===state.preview)||pages[0];try{const cv=await canvasPage(p,state.ratio);if(token!==renderToken)return;const target=$('#previewCanvas');target.width=cv.width;target.height=cv.height;target.getContext('2d').drawImage(cv,0,0);$('#previewTitle').textContent=p.title;}catch(e){if(token===renderToken){$('#previewTitle').textContent='预览失败：'+e.message;}}}
  const blobCanvas = cv=>new Promise((resolve,reject)=>cv.toBlob(b=>b?resolve(b):reject(Error('无法生成PNG')),'image/png'));
  function download(blob,name){const link=document.createElement('a'),url=URL.createObjectURL(blob);link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);}
  const filename = p => `${data.year}-${String(pages.indexOf(p)+1).padStart(2,'0')}-${p.id.replace(/[^a-zA-Z0-9_-]/g,'-').slice(0,80)||'page'}.png`;
  async function runExport(task){if(state.busy)return;state.busy=true;$('#ratio').disabled=true;drawShare();$('#exportStatus').textContent='正在准备字体、书封与分享画布…';try{await task();$('#exportStatus').textContent='下载已发起，请查看浏览器下载记录。';}catch(e){$('#exportStatus').textContent='导出失败：'+e.message+'。已保留选择，可以重试。';}finally{state.busy=false;$('#ratio').disabled=false;drawShare();}}
  $('#exportOne').onclick=()=>runExport(async()=>{const p=pages.find(p=>p.id===state.preview);const cv=await canvasPage(p,state.ratio);download(await blobCanvas(cv),filename(p));});
  // Dependency-free stored ZIP. CRC32 + UTF8 filenames; tested against Python zipfile.
  function crc32(bytes){let c=0xffffffff;for(const b of bytes){c^=b;for(let i=0;i<8;i++)c=(c>>>1)^((c&1)?0xedb88320:0);}return(c^0xffffffff)>>>0;}
  async function zip(files){const enc=new TextEncoder(),chunks=[],central=[];let offset=0;const u16=(view,pos,v)=>view.setUint16(pos,v,true),u32=(view,pos,v)=>view.setUint32(pos,v,true);
    for(const f of files){const name=enc.encode(f.name),bytes=new Uint8Array(await f.blob.arrayBuffer()),crc=crc32(bytes),local=new Uint8Array(30+name.length),l=new DataView(local.buffer);u32(l,0,0x04034b50);u16(l,4,20);u16(l,6,0x800);u32(l,14,crc);u32(l,18,bytes.length);u32(l,22,bytes.length);u16(l,26,name.length);local.set(name,30);chunks.push(local,bytes);
      const entry=new Uint8Array(46+name.length),v=new DataView(entry.buffer);u32(v,0,0x02014b50);u16(v,4,20);u16(v,6,20);u16(v,8,0x800);u32(v,16,crc);u32(v,20,bytes.length);u32(v,24,bytes.length);u16(v,28,name.length);u32(v,42,offset);entry.set(name,46);central.push(entry);offset+=local.length+bytes.length;}
    const size=central.reduce((n,x)=>n+x.length,0),end=new Uint8Array(22),v=new DataView(end.buffer);u32(v,0,0x06054b50);u16(v,8,files.length);u16(v,10,files.length);u32(v,12,size);u32(v,16,offset);return new Blob([...chunks,...central,end],{type:'application/zip'});
  }
  $('#exportGroup').onclick=()=>runExport(async()=>{const chosen=pages.filter(p=>state.selection.has(p.id)),ratio=state.ratio,files=[];for(const [i,p] of chosen.entries()){$('#exportStatus').textContent=`正在生成第${i+1}／${chosen.length}页…`;files.push({name:filename(p),blob:await blobCanvas(await canvasPage(p,ratio))});}download(await zip(files),`${data.year}-reading-share.zip`);});
  function markdown(){
    const lines=[`# ${data.year}阅读年鉴`,'',`范围：${scope}${data.as_of?'；采集日期：'+data.as_of:''}`,'',`阅读时长：${duration(data.summary.seconds)}`,`读过：${value(data.summary.read)}本；年度汇总读完：${value(data.summary.finished)}本`,''];
    if(data.collection_status&&!data.collection_status.complete)lines.push(data.collection_status.message||'部分材料暂未取得。','');
    if(data.material_coverage)lines.push(`当前进度100%的书：${data.material_coverage.current_finished}本（与年度汇总分别统计）。`,'');
    for(const b of data.books){
      lines.push(`## ${b.title}`,'',`作者：${b.author}`,'',`阅读状态：${statusLabel(b)}`,'');
      if(b.note_coverage?.scope==='all_time')lines.push('笔记范围：本书全部历史记录。','');
      for(const [title,rows,key] of [['划线',b.highlights,'highlights'],['个人笔记',b.thoughts,'thoughts']]){
        lines.push(`### ${title}`,'');for(const n of rows)lines.push(n.text,'',`来源：${b.title} · ${n.created_at||'日期未记录'} · ${n.source_id||'未记录来源ID'}`,'');
        if(!rows.length)lines.push(emptyNotes(b,key),'');
      }
    }return lines.join('\n');
  }
  $('#exportMd').onclick=()=>download(new Blob([markdown()],{type:'text/markdown;charset=utf-8'}),`${data.year}-reading.md`);
  $('#exportJson').onclick=()=>{const copy=JSON.parse(JSON.stringify(data));copy.books.forEach(b=>{delete b.cover;delete b.review;delete b.full_text_search;delete b.full_text_review;});download(new Blob([JSON.stringify(copy,null,2)],{type:'application/json;charset=utf-8'}),`${data.year}-reading.json`);};
  $('#exportPdf').onclick=()=>{if(state.query||state.category||state.status!=='all')toast('PDF将使用当前筛选的书架范围');window.print();};
  addEventListener('beforeprint',()=>{drawBooks(true);$$('#timeline details').forEach(el=>{el.dataset.wasOpen=String(el.open);el.open=true;});$('#printDetails').innerHTML=visibleBooks().map(b=>`<article>${bookDetails(b,true)}</article>`).join('');});
  addEventListener('afterprint',()=>{$('#printDetails').replaceChildren();$$('#timeline details').forEach(el=>el.open=el.dataset.wasOpen==='true');drawBooks();});
  // Keep chapter indicator aligned to the currently visible section.
  if('IntersectionObserver'in window){const observer=new IntersectionObserver(entries=>{const active=entries.filter(e=>e.isIntersecting).sort((a,b)=>a.boundingClientRect.top-b.boundingClientRect.top)[0];if(active){$$('nav a').forEach(a=>a.getAttribute('href')==='#'+active.target.id?a.setAttribute('aria-current','location'):a.removeAttribute('aria-current'));}},{rootMargin:'-15% 0px -60% 0px'});['overview','shelf','quotes','share'].forEach(id=>observer.observe($('#'+id)));}
  enhanceSelect($('#ratio'));
  drawShare();
})();
