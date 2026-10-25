/* Editorial share artwork. Data-driven layouts; no external requests.
 * Chart encodings reuse the yearbook's lieflat line / rung / tick vocabulary.
 * Each canvas carries a local layout manifest for export regression checks. */
window.ReadingShareArtwork = (() => {
  'use strict';
  const C={paper:'#f7f2e5',ink:'#242822',muted:'#686c61',secondaryInk:'#454a41',quietBlue:'#506875',red:'#b84432',blue:'#305c78',gold:'#cba74e',green:'#607765',line:'#c9c4b3',cream:'#eee6d2'};
  const SERIF='ReadingSerif,"Noto Serif SC","Songti SC",SimSun,serif';
  const SANS='ReadingSans,"Noto Sans SC","Microsoft YaHei",sans-serif';
  const NUM='Georgia,"Noto Serif",serif';
  const palette=[C.blue,C.red,C.green,C.gold,'#97768b','#7a8875','#bd8261'];
  const known=n=>typeof n==='number'&&Number.isFinite(n);
  const amount=n=>known(n)?String(n):'—';
  const duration=n=>!known(n)?'未记录':n>=3600?`${Math.floor(n/3600)}小时${Math.floor(n%3600/60)}分钟`:`${Math.floor(n/60)}分钟`;
  const status=b=>b.progress==null?'进度未记录':b.progress>=100?'已读完':'在读';
  function create({data,art,loadImage}){
    const fonts=Promise.all([document.fonts.load('600 48px ReadingSerif'),document.fonts.load('400 32px ReadingSerif'),document.fonts.load('400 28px ReadingSans')]);
    const categories=new Map();for(const b of data.books)categories.set(b.category,(categories.get(b.category)||0)+1);
    const counts=[...categories].map(([name,count])=>({name,count})).sort((a,b)=>b.count-a.count||a.name.localeCompare(b.name,'zh'));
    const colors=new Map(counts.map((r,i)=>[r.name,palette[i%palette.length]]));
    const chartPalette=['#bd5143','#4477a1','#b8973b','#5c897c','#ac7b84','#897b9e','#71828b'];
    const chartColors=new Map([...categories].sort((a,b)=>b[1]-a[1]).map(([name],i)=>[name,chartPalette[i%chartPalette.length]]));
    const bookAccents=new Map(),bookColor=b=>bookAccents.get(b.book_id)||colors.get(b.category)||C.blue;
    async function coverAccent(b){
      if(!b.cover||bookAccents.has(b.book_id))return;
      const im=await loadImage(b.cover),cv=document.createElement('canvas');cv.width=cv.height=24;const c=cv.getContext('2d');c.drawImage(im,0,0,24,24);
      // Quantize colored cover pixels into legible ink hues. White / neutral paper
      // has no vote, and category-chart colors keep their own stable semantics.
      const inks=[C.red,C.blue,C.green,'#8a6825','#79596d','#675b40'],rgb=inks.map(h=>[1,3,5].map(i=>parseInt(h.slice(i,i+2),16))),votes=inks.map(()=>0),pixels=c.getImageData(0,0,24,24).data;
      for(let i=0;i<pixels.length;i+=4){const p=[pixels[i],pixels[i+1],pixels[i+2]],sat=Math.max(...p)-Math.min(...p);if(pixels[i+3]<180||sat<35||Math.min(...p)>210)continue;let best=0,dist=Infinity;rgb.forEach((r,k)=>{const v=r.reduce((s,a,j)=>s+(a-p[j])**2,0);if(v<dist){best=k;dist=v;}});votes[best]+=sat;}
      if(Math.max(...votes)>0)bookAccents.set(b.book_id,inks[votes.indexOf(Math.max(...votes))]);
    }
    const events=[],seenEvents=new Set();for(const b of data.books){
      if(b.start_date?.startsWith(String(data.year)))events.push({date:b.start_date.slice(0,10),type:'开始阅读',book:b});
      if(b.finish_date?.startsWith(String(data.year)))events.push({date:b.finish_date.slice(0,10),type:'读完',book:b});
      for(const [kind,rows]of [['划线',b.highlights],['笔记',b.thoughts]])for(const n of rows)if(n.created_at?.startsWith(String(data.year))){const key=`${b.book_id}|${kind}|${n.source_id||n.text+'|'+n.created_at}`;if(!seenEvents.has(key)){seenEvents.add(key);events.push({date:n.created_at.slice(0,10),type:kind,book:b});}}
    }
    events.sort((a,b)=>a.date.localeCompare(b.date)||a.book.book_id.localeCompare(b.book.book_id));
    const months=data.summary.monthly.slice(0,data.summary.complete_months);
    function drawing(cv,p){
      const ctx=cv.getContext('2d'),W=cv.width,H=cv.height,M=64,R=W-M;
      const manifest={version:'editorial-2',page:p.id,width:W,height:H,footerTop:H-84,text:[],charts:[],images:[],spacing:[],blocks:[]};cv.readingLayout=manifest;
      function text(str,x,y,{size=30,weight=400,font=SERIF,color=C.ink,align='left',italic=false,role='content'}={}){
        ctx.font=`${italic?'italic ':''}${weight} ${size}px ${font}`;ctx.fillStyle=color;ctx.textAlign=align;ctx.textBaseline='alphabetic';
        ctx.fillText(String(str),x,y);const metric=ctx.measureText(String(str));
        const box={text:String(str),x:x-metric.actualBoundingBoxLeft,y:y-metric.actualBoundingBoxAscent,w:metric.actualBoundingBoxLeft+metric.actualBoundingBoxRight,h:metric.actualBoundingBoxAscent+metric.actualBoundingBoxDescent,size,role};
        if(String(str).trim())manifest.text.push(box);ctx.textAlign='left';return box;
      }
      function lines(str,width,style){
        ctx.font=`${style.weight||400} ${style.size||30}px ${style.font||SERIF}`;const out=[];let line='';
        for(const ch of String(str).replace(/\r/g,'')){
          if(ch==='\n'){out.push(line);line='';continue;}
          if(ctx.measureText(line+ch).width>width&&line){
            if(/[，。！？；：、）》】”’]/.test(ch)){out.push(line.slice(0,-1));line=line.slice(-1)+ch;}
            else if(/[（《【“‘]$/.test(line)){out.push(line.slice(0,-1));line=line.slice(-1)+ch;}
            else{out.push(line);line=ch;}
          }else line+=ch;
        }if(line)out.push(line);return out;
      }
      function measureBlock(str,w,h,{size=36,min=32,weight=400,font=SERIF,leading=1.5}={}){
        let ls=[],descent=0;
        while(size>=min){ls=lines(str,w-8,{size,weight,font});ctx.font=`${weight} ${size}px ${font}`;descent=ctx.measureText('阅读Ag，。').actualBoundingBoxDescent;
          if((ls.length-1)*size*leading+size+descent<=h||size===min)break;size=Math.max(min,size-2);}
        const step=size*leading,max=Math.max(0,1+Math.floor((h-size-descent)/step)),cut=ls.length>max;ls=ls.slice(0,max);
        if(cut&&ls.length){let last=ls.at(-1);ctx.font=`${weight} ${size}px ${font}`;while(last&&ctx.measureText(last+'…').width>w-8)last=last.slice(0,-1);ls[ls.length-1]=last+'…';}
        return {rows:ls,size,step,cut,height:ls.length?size+(ls.length-1)*step+descent:0};
      }
      function block(str,x,y,w,h,style={}){
        const fit=measureBlock(str,w,h,style);if(!fit.rows.length)return {bottom:y,lines:0,cut:Boolean(str)};
        fit.rows.forEach((s,i)=>text(s,x,y+fit.size+i*fit.step,{...style,size:fit.size}));
        manifest.blocks.push({x,y,w,h,cut:fit.cut});return {bottom:y+fit.height,lines:fit.rows.length,cut:fit.cut};
      }
      function rect(x,y,w,h,fill,stroke){ctx.fillStyle=fill;ctx.fillRect(x,y,w,h);if(stroke){ctx.strokeStyle=stroke;ctx.lineWidth=1;ctx.strokeRect(x,y,w,h);}}
      function line(x1,y1,x2,y2,color=C.line,width=1){ctx.strokeStyle=color;ctx.lineWidth=width;ctx.beginPath();ctx.moveTo(x1,y1);ctx.lineTo(x2,y2);ctx.stroke();}
      function dot(x,y,r,color){ctx.fillStyle=color;ctx.beginPath();ctx.arc(x,y,r,0,Math.PI*2);ctx.fill();}
      function section(label,x,y,w,no){line(x,y-12,x+w,y-12);text(no||'',x,y+22,{font:NUM,size:25,color:C.red,italic:true});text(label,x+(no?45:0),y+22,{size:27,weight:500,font:SANS});return y+48;}
      function scribble(x,y,w,color=C.red){ctx.strokeStyle=color;ctx.lineWidth=2;ctx.beginPath();for(let i=0;i<=30;i++){const xx=x+w*i/30,yy=y+Math.sin(i*.85)*1.5+i*.05;i?ctx.lineTo(xx,yy):ctx.moveTo(xx,yy);}ctx.stroke();}
      function star(x,y,r,color=C.gold){for(let i=0;i<4;i++){const a=i*Math.PI/4;line(x-Math.cos(a)*r,y-Math.sin(a)*r,x+Math.cos(a)*r,y+Math.sin(a)*r,color,1.5);}}
      async function image(src,x,y,w,h,{angle=0,shadow=false,fit='contain'}={}){
        const im=await loadImage(src),s=fit==='contain'?Math.min(w/im.width,h/im.height):Math.max(w/im.width,h/im.height),iw=im.width*s,ih=im.height*s;
        ctx.save();ctx.translate(x+w/2,y+h/2);ctx.rotate(angle*Math.PI/180);if(shadow){ctx.shadowColor='#31312630';ctx.shadowBlur=16;ctx.shadowOffsetX=5;ctx.shadowOffsetY=10;}
        if(fit==='cover'){ctx.beginPath();ctx.rect(-w/2,-h/2,w,h);ctx.clip();}ctx.drawImage(im,-iw/2,-ih/2,iw,ih);ctx.restore();
        const rad=angle*Math.PI/180,bw=Math.abs(iw*Math.cos(rad))+Math.abs(ih*Math.sin(rad)),bh=Math.abs(iw*Math.sin(rad))+Math.abs(ih*Math.cos(rad));
        manifest.images.push({x:x+w/2-bw/2,y:y+h/2-bh/2,w:bw,h:bh,angle});
      }
      async function cover(b,x,y,w,h,opts={}){if(b.cover)await image(b.cover,x,y,w,h,opts);else{rect(x,y,w,h,C.cream);block(b.title,x+18,y+22,w-36,h-44,{size:34,min:28,weight:600});}}
      function metric(n,label,x,y,w,{size=64,color=C.ink,labelY,labelSize=26}={}){
        const s=amount(n);let fs=size;ctx.font=`400 ${fs}px ${NUM}`;while(ctx.measureText(s).width>w-8&&fs>28){fs-=2;ctx.font=`400 ${fs}px ${NUM}`;}
        const numberBox=text(s,x,y,{size:fs,font:NUM,color});
        // Labels in a row share a baseline, even when a long value shrinks.
        ctx.font=`400 ${size}px ${NUM}`;const descent=ctx.measureText('0123456789').actualBoundingBoxDescent;
        ctx.font=`400 ${labelSize}px ${SANS}`;const ascent=ctx.measureText('阅读小时分钟').actualBoundingBoxAscent;
        const labelBox=text(label,x,labelY??y+descent+ascent+18,{size:labelSize,font:SANS,color:C.muted});
        manifest.spacing.push({kind:'metric',gap:labelBox.y-numberBox.y-numberBox.h,minimum:14,labelY:labelBox.y+labelBox.h});
      }
      function progress(b,x,y,w){
        if(!known(b.progress))return;const v=Math.max(0,Math.min(100,b.progress));text('当前进度',x,y,{size:26,font:SANS,color:C.muted});text(`${v}%`,x+w,y,{size:30,font:NUM,align:'right',color:bookColor(b)});
        rect(x,y+18,w,8,C.cream);rect(x,y+18,w*v/100,8,bookColor(b));manifest.charts.push({kind:'progress',value:v,width:w*v/100,totalWidth:w});
      }
      function trend(x,y,w,h,{small=false}={}){
        const vals=months,valid=vals.map((v,i)=>({v,i})).filter(r=>known(r.v));
        if(!valid.length){
          if(small)text('月度时长未记录',x,y+h/2+10,{size:25,font:SANS,color:C.muted});
          else block('暂无月度阅读时长记录。',x,y+35,w,h-35,{size:32,min:30,color:C.muted});
          return;
        }
        const top=Math.ceil(Math.max(...valid.map(r=>r.v/3600),1)/2)*2,left=x+(small?8:42),right=x+w-16,base=y+h-44,upper=y+26;
        if(!small)for(const v of [0,top/2,top]){const yy=base-v/top*(base-upper);line(left,yy,right,yy);text(String(v),x,yy+8,{size:25,font:NUM,color:C.muted});}
        const points=vals.map((v,i)=>known(v)?{value:v,month:i+1,x:vals.length===1?(left+right)/2:left+i*(right-left)/(vals.length-1),y:base-v/3600/top*(base-upper)}:null);
        ctx.strokeStyle=C.red;ctx.lineWidth=small?2:3;ctx.beginPath();let active=false;for(const pt of points){if(!pt){active=false;continue;}active?ctx.lineTo(pt.x,pt.y):ctx.moveTo(pt.x,pt.y);active=true;}ctx.stroke();
        const peak=valid.reduce((a,b)=>b.v>a.v?b:a);for(const pt of points)if(pt)dot(pt.x,pt.y,small?3:5,pt.month===peak.i+1?C.blue:C.red);
        if(!small){for(let i=0;i<vals.length;i++){const xx=vals.length===1?(left+right)/2:left+i*(right-left)/(vals.length-1);if(vals.length<=9||i%2===0||i===vals.length-1)text(`${i+1}月`,xx,base+35,{size:25,font:SANS,color:C.muted,align:'center'});}text('小时',x,y+5,{size:23,font:SANS,color:C.muted});}
        manifest.charts.push({kind:'monthly',points,top,base,upper});
      }
      function durationBar(v,max,x,y,w,color=C.blue){
        const width=max>0?w*v/max:0;
        rect(x,y-11,w,12,C.cream);
        for(const fraction of [.25,.5,.75])line(x+w*fraction,y-14,x+w*fraction,y+4,C.line,.7);
        rect(x,y-11,width,12,color);
        manifest.charts.push({kind:'duration-bar',value:v,max,width,totalWidth:w});
      }
      function base(){
        rect(0,0,W,H,C.paper);for(const [x,y,color]of [[W,0,'#e0bf65'],[0,H,'#90b5c7'],[W,H*.7,'#dda18e']]){const g=ctx.createRadialGradient(x,y,0,x,y,420);g.addColorStop(0,color+'38');g.addColorStop(1,color+'00');ctx.fillStyle=g;ctx.fillRect(0,0,W,H);}
        let seed=281;ctx.fillStyle='#635237';ctx.globalAlpha=.045;for(let i=0;i<3600;i++){seed=(Math.imul(seed,1664525)+1013904223)>>>0;const x=seed%W;seed=(Math.imul(seed,1664525)+1013904223)>>>0;ctx.fillRect(x,seed%H,1,1);}ctx.globalAlpha=1;
        ctx.strokeStyle=C.line;ctx.lineWidth=1;ctx.strokeRect(22,22,W-44,H-44);text('年年阅',M,72,{size:28,weight:600});
        const labels={cover:'阅读年鉴',stats:'阅读的节奏',distribution:'阅读分布',timeline:'阅读时间线',book:'书页之间'};
        text(labels[p.kind],W/2,71,{font:SANS,size:24,align:'center',color:C.muted});text(`${data.year}${data.source_mode==='sample'?' · 示例':''}`,R,72,{font:NUM,size:27,align:'right'});line(M,95,R,95);
        const idx=p.kind==='book'?5+data.books.findIndex(b=>b.book_id===p.book.book_id):['cover','stats','distribution','timeline'].indexOf(p.kind)+1;
        line(M,H-84,R,H-84);
        text(`${String(idx).padStart(2,'0')} / ${String(4+data.books.length).padStart(2,'0')}`,M,H-44,{font:NUM,size:24,color:C.muted,role:'footer'});
        text(p.kind==='book'?(p.quote?(p.textKind==='thought'?'个人笔记与阅读记录':'原文摘录与阅读记录'):'阅读记录'):'我的阅读年鉴',R,H-44,{size:23,font:SANS,align:'right',color:C.muted,role:'footer'});
      }
      return {ctx,W,H,M,R,text,block,measureBlock,rect,line,dot,section,scribble,star,image,cover,metric,progress,trend,durationBar,base,manifest};
    }
    async function render(p,ratio){
      await fonts;await document.fonts.ready;const cv=document.createElement('canvas');cv.width=900;cv.height=ratio==='1:1'?900:ratio==='4:5'?1125:1200;
      const D=drawing(cv,p);if(!D.ctx)throw Error('浏览器不支持Canvas');D.base();
      if(p.kind==='cover')await coverPage(D);
      else if(p.kind==='stats')await statsPage(D);
      else if(p.kind==='distribution')await distributionPage(D);
      else if(p.kind==='timeline')await timelinePage(D);
      else{await coverAccent(p.book);await bookPage(D,p);}
      return cv;
    }
    async function coverPage(d){
      const {H,M,R,text,block,line,image,cover,metric,trend,star}=d,square=H===900;
      text(String(data.year),M,square?215:238,{font:NUM,size:square?116:136,color:C.red,italic:true});
      await image(art.reading,568,125,260,126);
      text('这一年，',M,square?286:318,{size:square?52:58,weight:600});
      text('读了这些书',M,square?363:400,{size:square?64:72,weight:600});
      d.scribble(M,square?383:422,350,C.blue);star(797,square?341:373,14);
      const shelfTop=square?414:464,shelfBottom=square?622:H-371,shelfHeight=shelfBottom-shelfTop;
      const chosen=[...data.books.filter(b=>b.selected),...data.books.filter(b=>!b.selected)].slice(0,5);
      if(chosen.length){
        const cw=chosen.length<=2?190:Math.min(168,(R-M-56)/(chosen.length*.84+.16)),gap=cw*.84,total=cw+(chosen.length-1)*gap,left=(900-total)/2;
        for(const [i,b]of chosen.entries())await cover(b,left+i*gap,shelfTop+(i%2?12:0),cw,shelfHeight-24,{angle:[-4,3,-2,4,-3][i],shadow:true});
      }else{
        await image(art.hero,220,shelfTop,460,shelfHeight-62);
        block(data.coverage.complete?'这一年，还没有读书记录。':'阅读记录尚未取得。',M,shelfBottom-42,R-M,42,{size:28,min:26,color:C.muted});
      }
      line(M,shelfBottom+23,R,shelfBottom+23);
      const my=square?695:H-289,w=(R-M)/4;
      for(const [i,[v,label]]of [[data.summary.read,'本读过'],[data.summary.finished,'本读完'],[data.summary.read_days,'天阅读'],[data.summary.notes,'条笔记']].entries())metric(v,label,M+i*w,my,w-22,{size:square?52:60,color:C.secondaryInk,labelSize:24});
      const timeY=square?795:H-132;
      text('阅读时长',M,timeY,{font:SANS,size:24,color:C.muted});
      text(duration(data.summary.seconds),M+130,timeY,{font:SANS,size:square?28:30,color:C.quietBlue});
      if(!square)trend(475,H-181,345,90,{small:true});
    }
    async function statsPage(d){
      const {H,M,R,text,block,line,metric,trend,section}=d,square=H===900;
      text('今年，花在书上的时间',M,175,{size:52,weight:600});
      const total=data.summary.seconds;
      if(known(total)){
        metric(Math.floor(total/3600),'小时',M,281,338,{size:80,color:C.red,labelY:335});
        metric(Math.floor(total%3600/60),'分钟',M+405,281,330,{size:80,color:C.blue,labelY:335});
        line(M+365,215,M+365,340);
      }else text('阅读时长未记录',M,286,{size:42,color:C.muted});
      const w=(R-M)/4;
      for(const [i,[v,label]]of [[data.summary.read,'本读过'],[data.summary.finished,'本读完'],[data.summary.read_days,'天阅读'],[data.summary.notes,'条笔记']].entries())metric(v,label,M+i*w,410,w-22,{size:52});
      section('每月的阅读节奏',M,490,R-M,'01');
      const chartY=549,chartH=square?206:H-895;
      trend(M,chartY,R-M,chartH);
      const valid=months.map((v,i)=>({v,i})).filter(r=>known(r.v)),peakY=square?791:H-300;
      if(valid.length){const peak=valid.reduce((a,b)=>b.v>a.v?b:a);text(`${peak.i+1}月读得最久`,M,peakY,{size:27,weight:400,color:C.quietBlue});text(duration(peak.v),R,peakY,{size:26,font:SANS,align:'right',color:C.muted});}
      if(!square){
        const ranked=data.books.filter(b=>known(b.reading_seconds)&&b.reading_seconds>0).sort((a,b)=>b.reading_seconds-a.reading_seconds).slice(0,2);
        line(M,H-264,R,H-264);
        text('02',M,H-230,{font:NUM,size:24,color:C.red,italic:true});
        text(ranked.length?'时间花在哪本书上':'这一年的阅读记录',M+45,H-230,{size:26,weight:500,font:SANS,color:C.secondaryInk});
        if(ranked.length){
          const max=ranked[0].reading_seconds;
          for(const [i,b]of ranked.entries()){
            const y=H-171+i*60,style={size:28,min:26,weight:400,color:C.secondaryInk,leading:1.2};
            const shortTitle=measureBlockTitle(b.title);
            await d.cover(b,M,y-30,24,34);
            block(shortTitle,M+38,y-28,285,42,style);
            d.durationBar(b.reading_seconds,max,425,y-3,180,chartColors.get(b.category)||C.blue);
            text(duration(b.reading_seconds),R,y,{size:24,font:SANS,align:'right',color:C.muted});
          }
        }else block('每一本书，都在书架里留下了位置。',M,H-175,R-M,56,{size:28,min:26,color:C.muted});
      }
      function measureBlockTitle(title){return d.measureBlock(title,350,42,{size:28,min:26,leading:1.2}).cut&&/[：:]/.test(title)?title.split(/[：:]/)[0]:title;}
    }
    async function distributionPage(d){
      const {H,M,R,text,block,line,cover,section}=d,square=H===900;
      text('今年，读向了哪些地方',M,175,{size:54,weight:600});
      d.metric(data.books.length,'本读过',M,272,250,{size:66,color:C.red});
      text(`${counts.length}个分类`,R,270,{size:29,align:'right',font:SANS,color:C.muted});
      if(!counts.length){
        block(data.coverage.complete?'这一年没有可统计的阅读书目。':'暂未取得书目，暂无法展示分类分布。',M,371,R-M,118,{size:34,min:32});
        await d.image(art.hero,210,510,480,H-618);return;
      }
      const limit=square?4:6,rows=counts.slice(0,counts.length>limit?limit-1:limit);
      if(counts.length>limit)rows.push({name:'其他分类',count:counts.slice(limit-1).reduce((s,r)=>s+r.count,0),other:true});
      const max=Math.max(...rows.map(r=>r.count)),unit=Math.max(1,Math.ceil(max/(square?5:7)));
      section(`按分类统计 · 一块书脊${unit}本`,M,357,R-M,'01');
      const y0=415,bottom=square?638:H-344,rh=(bottom-y0)/Math.ceil(rows.length/2),categoryCell=(R-M)/2;
      for(const [i,r]of rows.entries()){
        const cy=y0+(Math.floor(i/2)+.5)*rh,x=M+(i%2)*categoryCell,color=chartColors.get(r.name)||C.green,marks=Math.ceil(r.count/unit),glyphs=[];
        block(r.name,x+130,cy-40,categoryCell-146,38,{size:29,min:26,weight:500,leading:1.2});
        text(`${r.count}本 · ${Math.round(r.count/data.books.length*100)}%`,x+130,cy+35,{font:SANS,size:27,color:C.muted});
        for(let k=0;k<marks;k++){
          const value=Math.min(unit,r.count-k*unit),h=10*value/unit,bx=x+15+[0,3,-1][k%3],by=cy+36-k*14-h;
          d.rect(bx+1,by+2,88,h,'#40352718');d.rect(bx,by,88,h,color);d.rect(bx+65,by+1,18,Math.max(0,h-2),C.paper);line(bx+8,by+2,bx+8,by+Math.max(2,h-2),C.cream,1);
          glyphs.push({value,x:bx,y:by,width:88,height:h});
        }
        d.manifest.charts.push({kind:'category',encoding:'book-spines',name:r.name,count:r.count,total:data.books.length,unit,marks,center:cy,glyphs});
      }
      const bottomY=square?656:H-284;
      section('从这些书，继续翻下去',M,bottomY,R-M,'02');
      const chosen=rows.filter(r=>!r.other).map(r=>data.books.find(b=>b.category===r.name)).slice(0,square?4:5),cell=(R-M)/chosen.length,cw=square?91:104,ch=square?86:127;
      for(const [i,b]of chosen.entries())await cover(b,M+i*cell+(cell-cw)/2,bottomY+54,cw,ch,{shadow:true});
    }
    async function timelinePage(d){
      const {H,M,R,text,block,line,dot,cover,section}=d,square=H===900;
      text('顺着这一年翻回去',M,175,{size:56,weight:600});
      text('有日期的阅读与笔记记录',M,226,{size:27,font:SANS,color:C.muted});
      if(!events.length){block('暂无带日期的阅读记录。',M,350,R-M,74,{size:34,min:32});await d.image(art.hero,190,464,520,H-578);return;}
      const buckets=new Map();for(const e of events){const k=e.date.slice(0,7);if(!buckets.has(k))buckets.set(k,[]);buckets.get(k).push(e);}
      const entries=[...buckets],limit=square?3:4,chosen=entries.length<=limit?entries:Array.from({length:limit},(_,i)=>entries[Math.round(i*(entries.length-1)/(limit-1))]);
      section('月份里的书页',M,289,R-M,'01');
      const top=354,bottom=H-169,rh=(bottom-top)/chosen.length;
      line(198,top+23,198,bottom-20,C.blue,1.5);
      for(const [i,[month,items]]of chosen.entries()){
        const y=top+i*rh,representative=items.find(e=>e.type==='读完')||items.find(e=>e.type==='开始阅读')||items[0];
        text(month.slice(5)+'月',M,y+45,{font:NUM,size:40,color:C.blue});dot(198,y+31,5,C.red);
        const ch=Math.min(119,rh-43);await cover(representative.book,231,y+12,84,ch,{shadow:false});
        block(representative.book.title,345,y+2,R-345,Math.min(102,rh-65),{size:32,min:28,weight:500,leading:1.35});
        const metaY=y+rh-24;
        text(`${representative.date.slice(5).replace('-','.')} · ${representative.type}`,345,metaY,{size:25,font:SANS,color:C.muted});
        text(`${items.length}条记录`,R,metaY,{size:25,font:SANS,color:C.blue,align:'right'});
        if(i<chosen.length-1)line(231,y+rh-9,R,y+rh-9);
      }
      text(`展示${chosen.length}个有记录的月份`,M,H-119,{size:25,font:SANS,color:C.muted});
      text(`共${events.length}条日期记录`,R,H-119,{size:25,font:SANS,color:C.blue,align:'right'});
      d.manifest.charts.push({kind:'timeline',total:events.length,months:buckets.size,shown:chosen.map(([month,items])=>({month,count:items.length}))});
    }
    async function bookPage(d,p){
      const {H,M,R,text,block,measureBlock,line,cover}=d,b=p.book,square=H===900,color=bookColor(b);
      const parts=b.title.match(/^(.{2,24}?)[：:]\s*(.+)$/);
      let title;
      if(parts){
        const main=block(parts[1],M,127,R-M,133,{size:58,min:36,weight:600,leading:1.2});
        title=block(parts[2],M,main.bottom+19,R-M,114,{size:38,min:30,weight:400,leading:1.35});
      }else{
        let size=56;
        // Avoid a lone final character in a headline; fit by the text, not by scaling the canvas.
        for(;size>36;size-=2){const fit=measureBlock(b.title,R-M,220,{size,min:size,weight:600,leading:1.2});if(!fit.cut&&(fit.rows.length<=1||fit.rows.at(-1).trim().length>=4))break;}
        title=block(b.title,M,127,R-M,220,{size,min:32,weight:600,leading:1.2});
      }
      const author=block(b.author,M,title.bottom+24,R-M,67,{size:27,min:25,font:SANS,color:C.muted,leading:1.35});
      const bodyY=author.bottom+32,mainBottom=H-260,available=mainBottom-bodyY;
      const primary=p.quote||'',kind=p.textKind==='thought'?'个人笔记':'原文摘录',rich=Boolean(primary),long=primary.length>(square?75:130);
      const bodyStyle={size:30,min:30,weight:400,font:SERIF,color:C.secondaryInk,leading:1.65,role:'book-body'};
      let excerpted=false;
      function excerpt(str,x,y,w,h,label){
        const fit=measureBlock(str,w,h,bodyStyle);excerpted=excerpted||fit.cut;
        text(label+(fit.cut?' · 节选':''),x,y-20,{size:24,weight:400,font:SANS,color,role:'book-label'});
        return block(str,x,y,w,h,bodyStyle);
      }
      if(available<140)throw Error('书名或作者过长，分享页内容超出安全版面，请缩短展示标题。');
      if(rich&&!long){
        const coverH=Math.min(330,available-90),qx=M+286,qw=R-qx;
        await cover(b,M+7,bodyY+8,222,coverH,{angle:-2,shadow:true});
        line(M+254,bodyY+5,M+254,mainBottom-9,color,1);
        const q=excerpt(primary,qx,bodyY+57,qw,available-63,kind);
        const secondary=[...b.thoughts.map(n=>({...n,label:'我的笔记'})),...b.highlights.map(n=>({...n,label:'另一处划线'}))],seen=new Set([primary]);
        let nextTop=q.bottom+55,added=0;
        for(const n of secondary){
          if(seen.has(n.text)||added===2)continue;seen.add(n.text);
          const height=mainBottom-nextTop-8;
          if(height<64||measureBlock(n.text,qw,height,bodyStyle).cut)continue;
          const item=excerpt(n.text,qx,nextTop,qw,height,n.label);nextTop=item.bottom+55;added++;
        }
        const categoryY=bodyY+coverH+38;
        if(b.category&&categoryY+51<mainBottom)block(b.category,M+7,categoryY,222,59,{size:28,min:26,color,leading:1.3});
      }else if(rich){
        const cw=112,ch=Math.min(157,available-22),qx=M,qw=R-M-171;
        await cover(b,R-cw-3,bodyY+6,cw,ch,{angle:2,shadow:true});
        excerpt(primary,qx,bodyY+58,qw,available-66,kind);
        const cy=bodyY+ch+38;
        if(b.category&&cy+84<mainBottom)block(b.category,R-135,cy,135,84,{size:28,min:25,color,leading:1.4});
      }else if(b.intro){
        const cw=244,ch=Math.min(377,available-24),tx=M+312;
        await cover(b,M+9,bodyY+9,cw,ch,{angle:-2,shadow:true});
        line(M+279,bodyY+5,M+279,mainBottom-9,color,1);
        excerpt(b.intro,tx,bodyY+57,R-tx,available-63,'内容简介');
      }else{
        const cw=296,tx=M+370,tw=R-tx;
        await cover(b,M+15,bodyY+7,cw,available-19,{angle:-2,shadow:true});
        line(M+335,bodyY+5,M+335,mainBottom-9,color,1);
        let next=bodyY;
        if(known(b.progress)){
          text('阅读状态',tx,next+27,{size:25,font:SANS,color:C.muted});
          const state=block(status(b),tx,next+48,tw,61,{size:40,min:32,weight:500,color});next=state.bottom+36;
        }
        if(b.category&&b.category!=='未分类'&&next+75<mainBottom){
          text('分类',tx,next+24,{size:25,font:SANS,color:C.muted});
          const cat=block(b.category,tx,next+44,tw,78,{size:32,min:28,color,leading:1.35});next=cat.bottom+32;
        }
        if(mainBottom-next>=132)await d.image(art.hero,tx,next,tw,mainBottom-next-4);
      }
      const metricY=H-200,mx=M+280,mw=R-mx;
      line(M,metricY-30,R,metricY-30,color,1);
      const hComplete=b.note_coverage?.highlights==='complete',tComplete=b.note_coverage?.thoughts==='complete';
      const cols=[[known(b.reading_seconds)?`${Math.floor(b.reading_seconds/3600)}小时\n${Math.floor(b.reading_seconds%3600/60)}分钟`:null,'阅读时长'],[hComplete&&(rich||b.highlights.length)?String(b.highlights.length):null,'条划线'],[tComplete&&(rich||b.thoughts.length)?String(b.thoughts.length):null,'条个人笔记']].filter(([v])=>v!==null);
      if(known(b.progress))d.progress(b,M,metricY+19,cols.length?230:R-M);
      else if(cols.length)block(status(b),M,metricY+3,230,54,{size:28,min:26,color:C.muted});
      if(cols.length)for(const [i,[v,label]]of cols.entries()){
        const x=mx+i*mw/cols.length,w=mw/cols.length-23,isTime=label==='阅读时长';
        if(i)line(x-15,metricY-1,x-15,metricY+84);
        block(v,x,isTime?metricY-11:metricY+6,w,isTime?75:60,{size:isTime?28:44,min:26,font:isTime?SANS:NUM,leading:1.35,color:i===0?color:C.ink});
        text(label,x,metricY+92,{font:SANS,size:24,color:C.muted});
      }
      d.manifest.material={highlights:b.highlights.length,thoughts:b.thoughts.length,kind:rich?kind:'book-info',long,excerpted};
    }
    return {render};
  }
  // Digest cards keep every line. Pagination happens before drawing and the
  // same page descriptor is used by preview, PNG and ZIP.
  function createDigest({analysis}){
    const fonts=()=>document.fonts.ready;
    const titleMode=analysis.input_mode==='title',nonIsolated=Boolean(analysis.evaluation_limit)||titleMode,footerHeight=nonIsolated?132:84;
    // Detailed evidence and verification stay in the result's reference section.
    const exportLimits='';
    const height=ratio=>ratio==='1:1'?900:ratio==='4:5'?1125:1200;
    function wrap(ctx,str,width,size=32,font=SANS,weight=400){ctx.font=`${weight} ${size}px ${font}`;const rows=[];let line='';for(const ch of String(str).replace(/\r/g,'')){if(ch==='\n'){rows.push({text:line});line='';continue;}if(line&&ctx.measureText(line+ch).width>width){rows.push({text:line});line=ch;}else line+=ch;}if(line)rows.push({text:line});return rows;}
    async function pages(items,ratio){await fonts();const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');if(!ctx)throw Error('浏览器不支持 Canvas');const result=[],capacity=Math.floor((height(ratio)-270-(footerHeight-84))/48);for(const item of items){const limits=item.kind==='review'?'':exportLimits;const content=[...wrap(ctx,analysis.book?.title||'电子书精华',764,38,SERIF,600).map(r=>({...r,size:38,weight:600})),...wrap(ctx,analysis.book?.author||'',764).map(r=>({...r,size:32,weight:400})),{text:'',size:32},...wrap(ctx,item.title,764,38,SERIF,600).map(r=>({...r,size:38,weight:600})),{text:'',size:32},...wrap(ctx,item.text+limits,764).map(r=>({...r,size:32,weight:400}))];for(let start=0;start<content.length;start+=capacity)result.push({id:item.id+'-'+Math.floor(start/capacity),title:item.title,kind:item.kind,part:Math.floor(start/capacity)+1,parts:Math.ceil(content.length/capacity),rows:content.slice(start,start+capacity)});}return result;}
    async function render(page,ratio){await fonts();const canvas=document.createElement('canvas');canvas.width=900;canvas.height=height(ratio);const ctx=canvas.getContext('2d'),W=900,H=canvas.height,M=64;const manifest={version:'digest-1',page:page.id,width:W,height:H,footerTop:H-footerHeight,text:[],blocks:[],charts:[],images:[],spacing:[]};canvas.readingLayout=manifest;
      const text=(str,x,y,size=28,font=SANS,color=C.ink,weight=400,role='content')=>{ctx.font=`${weight} ${size}px ${font}`;ctx.fillStyle=color;ctx.textBaseline='alphabetic';ctx.fillText(str,x,y);const m=ctx.measureText(str);if(str.trim())manifest.text.push({text:str,x:x-m.actualBoundingBoxLeft,y:y-m.actualBoundingBoxAscent,w:m.actualBoundingBoxLeft+m.actualBoundingBoxRight,h:m.actualBoundingBoxAscent+m.actualBoundingBoxDescent,size,role});};
      const rule=y=>{ctx.strokeStyle=C.line;ctx.lineWidth=1;ctx.beginPath();ctx.moveTo(M,y);ctx.lineTo(W-M,y);ctx.stroke();};
      ctx.fillStyle=C.paper;ctx.fillRect(0,0,W,H);ctx.strokeStyle=C.line;ctx.strokeRect(22,22,W-44,H-44);text('年年阅',M,72,28,SERIF,C.ink,600);text('书中精华',530,72,24,SANS,C.muted);rule(95);
      page.rows.forEach((row,i)=>text(row.text,M,160+i*48,row.size||32,(row.weight||400)===600?SERIF:SANS,C.ink,row.weight||400));manifest.blocks.push({x:M,y:122,w:772,h:H-238-(footerHeight-84),cut:false});rule(H-footerHeight);if(nonIsolated){text(titleMode?'基于公开资料，未核验全文':'基于所提供正文 · 方法待核查',M,H-96,23,SANS,C.muted,400,'footer');text((analysis.reading_status?.level==='partial'?'部分解读 · ':'')+'出处与资料范围见结果页',M,H-64,23,SANS,C.muted,400,'footer');}text(`${page.part} / ${page.parts}`,M,H-(nonIsolated?32:44),24,NUM,C.muted,400,'footer');if(!nonIsolated)text((analysis.reading_status?.level==='partial'?'部分解读 · ':'')+'出处见结果页',400,H-44,23,SANS,C.muted,400,'footer');return canvas;
    }
    return {pages,render};
  }
  return {create,createDigest};
})();
