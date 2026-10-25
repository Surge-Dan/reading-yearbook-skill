/* Pass a yearbook fixture containing timed and untimed books. Uses installed
 * Playwright/Chromium only; no network, assets or browsers are downloaded. */
const {chromium}=require('playwright'),assert=require('assert'),fs=require('fs'),path=require('path'),{pathToFileURL}=require('url');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.BROWSER_EXECUTABLE||'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe'});
 const context=await browser.newContext(),page=await context.newPage(),checks=[],errors=[],requests=[];
 await context.setOffline(true);page.on('pageerror',e=>errors.push(e.message));page.on('request',r=>{if(/^https?:/.test(r.url()))requests.push(r.url());});
 await page.setViewportSize({width:1440,height:1050});await page.goto(pathToFileURL(path.resolve(process.argv[2])).href);await page.evaluate(()=>document.fonts.ready);
 const pass=name=>checks.push(name),data=await page.locator('#reading-data').evaluate(n=>JSON.parse(n.textContent));
 await page.waitForFunction(()=>[...document.querySelectorAll('[data-art]')].every(n=>n.complete&&n.naturalWidth>0));
 assert.equal(await page.locator('[data-art]').count(),3);pass('original illustration and complete lettering load offline');
 for(const id of ['chart','distribution','investment']){
   await page.locator('#'+id).scrollIntoViewIfNeeded();await page.locator(`[data-replay="${id}"]`).click();
   const started=await page.locator('#'+id).evaluate(n=>({state:n.dataset.motionState,animations:n.getAnimations({subtree:true}).length}));
   assert.equal(started.state,'playing');assert(started.animations>0,`${id} has no animations`);
   await page.waitForFunction(id=>document.getElementById(id).dataset.motionState==='complete',id);pass(`${id}: actual staggered animation, replay and completion`);
 }
 await page.locator('[data-replay="chart"]').scrollIntoViewIfNeeded();
 const bounded=await page.evaluate(()=>{const b=document.querySelector('[data-replay="chart"]');for(let i=0;i<12;i++)b.click();const n=document.querySelector('#chart');return n.getAnimations({subtree:true}).length<=n.querySelectorAll('.draw,.pop,.fade').length;});assert(bounded);pass('rapid replay cancels previous animations');
 await page.setViewportSize({width:390,height:1050});await page.waitForTimeout(80);
 assert.equal(await page.locator('#chart path').first().evaluate(n=>getComputedStyle(n).strokeDashoffset),'0px');
 assert.equal(await page.locator('#chart').getAttribute('data-motion-state'),'complete');pass('resize leaves final chart visible');
 assert.equal(await page.locator('.category-count').evaluateAll(ns=>ns.reduce((s,n)=>s+Number(n.textContent),0)),data.books.length);
 const expected=data.books.filter(b=>b.reading_seconds!=null).map(b=>b.reading_seconds).sort((a,b)=>b-a);
 assert.deepEqual(await page.locator('.tick-row').evaluateAll(ns=>ns.map(n=>Number(n.dataset.seconds))),expected);
 const represented=await page.locator('[data-spine-value]').evaluateAll(ns=>ns.reduce((s,n)=>s+Number(n.dataset.spineValue),0));assert.equal(represented,data.books.length);
 const exact=await page.locator('.tick-row').evaluateAll(ns=>{const max=Math.max(...ns.map(n=>Number(n.dataset.seconds)),1);return ns.every(n=>Math.abs(Number(n.querySelector('.duration-fill').getAttribute('width'))/480*max-Number(n.dataset.seconds))<1e-6);});assert(exact);pass('book spines preserve category totals; solid bars preserve fractional time and omit unknowns');
 await page.emulateMedia({reducedMotion:'reduce'});for(const id of ['chart','distribution','investment']){await page.locator(`[data-replay="${id}"]`).click();assert.equal(await page.locator('#'+id).getAttribute('data-motion-state'),'complete');assert.equal(await page.locator('#'+id).evaluate(n=>n.getAnimations({subtree:true}).length),0);}pass('reduced motion renders final frame without animations');
 await page.emulateMedia({reducedMotion:'no-preference'});await page.locator('[data-replay="chart"]').click();await page.emulateMedia({media:'print'});
 assert.equal(await page.locator('#chart path').first().evaluate(n=>getComputedStyle(n).strokeDashoffset),'0px');assert.equal(await page.locator('#chart').evaluate(n=>n.getAnimations({subtree:true}).length),0);pass('print uses complete chart while animation is running');
 assert.deepEqual(errors,[]);assert.deepEqual(requests,[]);pass('no network or runtime errors');
 const output=path.resolve(process.argv[3]||'demo-output/reading-art-tests/motion-report.json');fs.mkdirSync(path.dirname(output),{recursive:true});fs.writeFileSync(output,JSON.stringify({status:'pass',checks},null,2));await browser.close();console.log(JSON.stringify({status:'pass',checks:checks.length,output}));
})().catch(e=>{console.error(e);process.exit(1)});
