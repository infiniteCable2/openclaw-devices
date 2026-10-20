// Run with Node.js and Playwright available. Only synthetic, intercepted HTTP.
const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const {readFile, mkdir} = require('node:fs/promises');
const path = require('node:path');
const {chromium} = require('playwright');
let browser, html;
before(async () => {
  html = await readFile(path.join(__dirname, '../main/portal.html'), 'utf8');
  browser = await chromium.launch({headless:true, ...(process.env.PORTAL_BROWSER_PATH ? {executablePath:process.env.PORTAL_BROWSER_PATH} : {})});
});
after(async () => { await browser?.close(); });
const status = () => ({ssid:'Example A', wifiNetworks:[
  {ssid:'Example A',dns:'192.0.2.53',hidden:false,wifiPasswordSet:true},
  {ssid:'Hidden Example',dns:'',hidden:true,wifiPasswordSet:true}
],context:'node1',gateway:'wss://gateway.example.org',ca:'',mode:'allowlist',scan:false,ping:false,rules:[],
csrf:'synthetic-csrf',online:true,activeSsid:'Example A',rssi:-48,ip:'192.0.2.20',clockReady:true,gatewayReady:true});
async function fixture(options={}) {
  const context=await browser.newContext({viewport:options.mobile?{width:390,height:844}:{width:1100,height:900}});
  const page=await context.newPage(),posts=[],errors=[];let data={...status(),...options.status},scanReads=0;
  if(options.clock)await page.clock.install();
  page.on('pageerror',error=>errors.push(error.message));
  await page.route('http://127.0.0.1:8765/**',async route=>{
    const request=route.request(),url=new URL(request.url());
    if(url.pathname==='/')return route.fulfill({contentType:'text/html; charset=utf-8',body:html});
    if(request.method()==='POST'){
      assert.equal(request.headers()['x-csrf-token'],'synthetic-csrf');
      posts.push({path:url.pathname,body:request.postDataJSON()});return route.fulfill({status:200,body:'Saved'});
    }
    if(url.pathname==='/api/status')return route.fulfill({json:data});
    if(url.pathname==='/api/wifi/scan')return route.fulfill({json:{busy:++scanReads===1,error:'',networks:[
      {ssid:'<img src=x onerror=alert(1)>',rssi:-42,security:'WPA/WPA2/WPA3',supported:true},
      {ssid:'Open Example',rssi:-70,security:'Offen',supported:true},
      {ssid:'Enterprise Example',rssi:-80,security:'Nicht unterstützt',supported:false}
    ]}});
    throw Error(`Unexpected fixture URL ${url.pathname}`);
  });
  await page.goto('http://127.0.0.1:8765/');await page.waitForFunction(count=>document.querySelector('#profileCount').textContent===`(${count}/8)`,data.wifiNetworks.length);
  return {page,posts,errors,context,setStatus:value=>{data={...data,...value};}};
}
test('saved networks: preserve credentials, per-profile DNS, preferred selection and deletion',async()=>{
  const f=await fixture();try{
    await f.page.locator('.profile').nth(1).getByText('Bearbeiten').click();
    assert.equal(await f.page.locator('#wifiPassword').inputValue(),'');
    assert.equal(await f.page.locator('#hiddenWifi').isChecked(),true);
    await f.page.locator('#dns').fill('198.51.100.53');await f.page.locator('#preferWifi').check();await f.page.locator('#storeWifi').click();
    await f.page.locator('.profile').nth(0).getByText('Entfernen').click();await f.page.locator('#save').click();
    const body=f.posts.find(p=>p.path==='/api/settings').body;
    assert.equal(body.ssid,'Hidden Example');assert.deepEqual(body.wifiNetworks,[{ssid:'Hidden Example',dns:'198.51.100.53',hidden:true,clearWifiPassword:false}]);
    assert.equal(body.gateway,'wss://gateway.example.org');assert.deepEqual(f.errors,[]);
  }finally{await f.context.close();}
});
test('manual hidden SSID and automatic staging on save',async()=>{
  const f=await fixture();try{
    await f.page.locator('#ssid').fill('Hidden New Example');await f.page.locator('#wifiPassword').fill('example-new-secret');await f.page.locator('#hiddenWifi').check();
    await f.page.locator('#save').click();const body=f.posts[0].body;
    assert.equal(body.ssid,'Hidden New Example');assert.equal(body.wifiNetworks.length,3);
    assert.deepEqual(body.wifiNetworks[2],{ssid:'Hidden New Example',dns:'',hidden:true,clearWifiPassword:false,wifiPassword:'example-new-secret'});
    assert.deepEqual(f.errors,[]);
  }finally{await f.context.close();}
});
test('new SSID cannot silently reuse another password or become open',async()=>{
  const f=await fixture();try{
    await f.page.locator('.profile').nth(0).getByText('Bearbeiten').click();await f.page.locator('#ssid').fill('New Example');await f.page.locator('#save').click();
    assert.equal(f.posts.length,0);assert.match(await f.page.locator('#notice').textContent(),/Passwort/);
    await f.page.locator('#clearWifiPassword').check();await f.page.locator('#save').click();
    const profile=f.posts[0].body.wifiNetworks.at(-1);assert.equal(profile.clearWifiPassword,true);assert.equal(profile.wifiPassword,undefined);
  }finally{await f.context.close();}
});
test('deleting the last WLAN saves an empty list and no preferred SSID',async()=>{
  const f=await fixture();try{
    await f.page.locator('.profile').nth(0).getByText('Entfernen').click();await f.page.locator('.profile').nth(0).getByText('Entfernen').click();await f.page.locator('#save').click();
    assert.deepEqual(f.posts[0].body.wifiNetworks,[]);assert.equal(f.posts[0].body.ssid,'');
  }finally{await f.context.close();}
});
test('full list can free one slot without losing a pending new WLAN',async()=>{
  const wifiNetworks=status().wifiNetworks;
  for(let i=2;i<8;i++)wifiNetworks.push({ssid:`Example ${i}`,dns:'',hidden:false,wifiPasswordSet:true});
  const f=await fixture({status:{wifiNetworks}});try{
    await f.page.locator('#ssid').fill('New Example');await f.page.locator('#wifiPassword').fill('example-new-secret');
    await f.page.locator('#storeWifi').click();assert.match(await f.page.locator('#notice').textContent(),/acht/);
    await f.page.locator('.profile').last().getByText('Entfernen').click();
    assert.equal(await f.page.locator('#wifiPassword').inputValue(),'example-new-secret');
    await f.page.locator('#storeWifi').click();await f.page.locator('#save').click();
    assert.equal(f.posts[0].body.wifiNetworks.length,8);assert.equal(f.posts[0].body.ssid,'New Example');
  }finally{await f.context.close();}
});
test('asynchronous scan renders SSIDs as text, marks unsupported networks, selects open WLAN',async()=>{
  const f=await fixture();try{
    await f.page.locator('#searchWifi').click();await f.page.waitForFunction(()=>!document.querySelector('#foundWifi').disabled);
    assert.equal(await f.page.locator('img').count(),0);assert.match(await f.page.locator('#foundWifi').textContent(),/<img src=x onerror=alert\(1\)>/);
    assert.equal(await f.page.locator('#foundWifi option').last().evaluate(option=>option.disabled),true);
    await f.page.locator('#foundWifi').selectOption('Open Example');assert.equal(await f.page.locator('#ssid').inputValue(),'Open Example');assert.equal(await f.page.locator('#clearWifiPassword').isChecked(),true);
    assert.deepEqual(f.errors,[]);
  }finally{await f.context.close();}
});
test('periodic status does not overwrite unsaved edits',async()=>{
  const f=await fixture({clock:true});try{
    await f.page.locator('#context').fill('node-draft');await f.page.locator('#ssid').fill('Unsaved Example');await f.page.locator('#wifiPassword').fill('example-draft-secret');
    f.setStatus({activeSsid:'Hidden Example',rssi:-60});await f.page.clock.runFor(15500);
    await f.page.waitForFunction(()=>document.querySelector('#wifiState').textContent.includes('Hidden Example'));
    assert.equal(await f.page.locator('#context').inputValue(),'node-draft');assert.equal(await f.page.locator('#wifiPassword').inputValue(),'example-draft-secret');
    assert.match(await f.page.locator('#wifiState').textContent(),/Hidden Example/);assert.deepEqual(f.errors,[]);
  }finally{await f.context.close();}
});
test('desktop and mobile layout remain within viewport',async()=>{
  for(const mobile of [false,true]){
    const f=await fixture({mobile});try{
      assert.equal(await f.page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true);
      if(process.env.PORTAL_SCREENSHOT_DIR){await mkdir(process.env.PORTAL_SCREENSHOT_DIR,{recursive:true});await f.page.screenshot({path:path.join(process.env.PORTAL_SCREENSHOT_DIR,mobile?'portal-mobile.jpg':'portal-desktop.jpg'),type:'jpeg',quality:80,fullPage:true});}
      assert.deepEqual(f.errors,[]);
    }finally{await f.context.close();}
  }
});
