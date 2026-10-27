/* Controlled sample bundles only; does not evaluate real books or model quality. */
const {chromium}=require('playwright');
const assert=require('assert'),fs=require('fs'),path=require('path'),os=require('os');
const input=path.resolve(process.argv[2]||'demo-output/assistant-report-20261026/index.html');
const out=fs.mkdtempSync(path.join(os.tmpdir(),'reading-reader-'));
(async()=>{
  const browser=await chromium.launch({headless:true,executablePath:'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
  try{
    const context=await browser.newContext({acceptDownloads:true}),page=await context.newPage(),errors=[],requests=[];
    page.on('pageerror',e=>errors.push(e.message));
    page.on('request',r=>requests.push(r.url()));
    await page.goto(require('url').pathToFileURL(input).href);
    await page.locator('#ebookBookTitle').getByText('门口那盏灯', {exact:false}).waitFor();
    assert.equal(await page.locator('#ebookBookSelect option').count(),2);
    assert.equal(await page.locator('#ebookUpload,#ebookTask,#ebookStartInstruction,#ebookConnection').count(),0);
    assert((await page.locator('#ebookResult').textContent()).includes('故事的底色'));
    assert((await page.locator('#ebookResult').textContent()).includes('值得保留的金句'));
    const stats=await page.locator('#stats').textContent();
    await page.evaluate(()=>{Object.defineProperty(navigator,'clipboard',{value:{writeText:async text=>window.copied=text},configurable:true});});
    await page.locator('#ebookCopyAll').click();
    assert((await page.evaluate(()=>window.copied)).includes('门口那盏灯'));
    await page.locator('#ebookBookSelect').selectOption('1');
    await page.locator('#ebookBookTitle').getByText('一场差点开不成的会',{exact:false}).waitFor();
    assert.equal(await page.locator('#stats').textContent(),stats);
    assert(!(await page.locator('#ebookResult').textContent()).includes('林叔'));
    await page.locator('#ebookCopyAll').click();
    const copied=await page.evaluate(()=>window.copied);
    assert(copied.includes('一场差点开不成的会'));
    assert(!copied.includes('林叔'));
    assert(copied.includes('读完想试的一件事'));
    await page.locator('#ebook-reading-passages [data-ebook-copy]').first().click();
    const passageCopy=await page.evaluate(()=>window.copied);
    assert(passageCopy.startsWith('原文：\n'),'single-passage copy identifies the original text');
    assert(passageCopy.includes('为什么记住它：'),'single-passage copy separates interpretation');
    const footer=await page.evaluate(async()=>{const a=window.EBOOK_RESULT.analysis,art=ReadingShareArtwork.createDigest({analysis:a}),pages=await art.pages([{id:'scope',kind:'reading_lenses',title:a.reading_lenses[0].title,text:a.reading_lenses[0].text}],'3:4'),canvas=await art.render(pages[0],'3:4');return canvas.readingLayout.text.filter(row=>row.role==='footer').map(row=>row.text).join(' ');});
    assert.deepEqual({copyScope:copied.includes('基于所提供正文'),imageScope:footer.includes('基于所提供正文')},{copyScope:true,imageScope:true},'exports retain the current source boundary');
    async function download(id){
      const [dl]=await Promise.all([page.waitForEvent('download'),page.locator(id).click()]);
      const file=path.join(out,dl.suggestedFilename());await dl.saveAs(file);return {file,bytes:fs.readFileSync(file)};
    }
    assert.equal((await download('#ebookDownloadMd')).bytes.toString(),copied);
    const exported=await download('#ebookDownloadHtml');
    assert(!exported.bytes.toString().includes('id="ebookBookSelect"'));
    const offline=await context.newPage();offline.on('pageerror',e=>errors.push(e.message));offline.on('request',r=>requests.push(r.url()));
    await offline.goto(require('url').pathToFileURL(exported.file).href);
    await offline.locator('#ebookBookTitle').getByText('一场差点开不成的会',{exact:false}).waitFor();
    assert((await offline.locator('#ebookResult').textContent()).includes('给未知留一行'));
    assert.equal(await offline.locator('#ebookUpload,#ebookTask').count(),0);
    await page.setViewportSize({width:375,height:812});
    assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)), '375px report overflow');
    await page.locator('#ebookShareToggle').click();
    await page.waitForFunction(()=>document.querySelector('#ebookPage').options.length>0&&!document.querySelector('#ebookExportPng').disabled);
    assert(!(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)), '375px share overflow');
    const preview=await page.locator('#ebookCanvas').evaluate(c=>c.toDataURL().split(',')[1]);
    const png=await download('#ebookExportPng');
    assert.equal(png.bytes.toString('base64'),preview,'selected-book preview must equal exported PNG');
    const pages=await page.locator('#ebookPage option').count(),zip=(await download('#ebookExportZip')).bytes;
    assert.equal(zip.readUInt32LE(zip.length-22),0x06054b50);assert.equal(zip.readUInt16LE(zip.length-12),pages);
    await page.locator('#ebookBookSelect').selectOption('0');
    await page.waitForFunction(()=>document.querySelector('#ebookPage').options.length>0&&!document.querySelector('#ebookExportPng').disabled);
    assert((await page.locator('#ebookBookTitle').textContent()).includes('门口那盏灯'));
    assert.notEqual(await page.locator('#ebookCanvas').evaluate(c=>c.toDataURL().split(',')[1]),preview,'switching replaces selected-book share canvas');
    const colors=await page.evaluate(()=>({body:getComputedStyle(document.body).backgroundImage,paper:getComputedStyle(document.querySelector('.paper')).backgroundImage,button:getComputedStyle(document.querySelector('#ebookCopyAll')).borderRadius}));
    assert.deepEqual(colors,{body:'none',paper:'none',button:'8px'});
    await page.locator('#ebook').screenshot({path:path.join(out,'reader-375.png')});
    assert.deepEqual(errors,[]);assert(!requests.some(url=>/^https?:/.test(url)), 'offline report makes no HTTP requests');
    console.log(JSON.stringify({status:'PASS',checks:'two-book readonly, optional reading fields, copy, MD/HTML/PNG/ZIP, switching share, unchanged annual stats, 375px, no HTTP requests/page errors',output:out}));
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
