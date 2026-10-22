const {test} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '../chrome_extension');

test('offscreen parser accepts Amazon inline CSS without CSP errors and keeps fetched HTML inert', async () => {
  const server = http.createServer((req,res) => {
    const file = path.join(root,new URL(req.url,'http://localhost').pathname);
    if (!fs.existsSync(file)) {res.writeHead(404);res.end();return;}
    res.setHeader('Content-Type',file.endsWith('.html') ? 'text/html' : 'text/javascript');
    res.end(fs.readFileSync(file));
  });
  await new Promise(r=>server.listen(0,'127.0.0.1',r));
  let browser;
  try {
    browser = await chromium.launch({headless:true,...(process.env.PW_CHROMIUM_EXECUTABLE ? {executablePath:process.env.PW_CHROMIUM_EXECUTABLE} : {})});
    const context = await browser.newContext();
    const externalRequests = [];
    await context.route('https://parser-fixture.invalid/**',route => {externalRequests.push(route.request().url());return route.abort();});
    await context.addInitScript(() => {
      window.__parserListeners = [];
      window.chrome = {runtime:{id:'fixture',onMessage:{addListener:listener=>window.__parserListeners.push(listener)}}};
    });
    const page = await context.newPage();
    const consoleErrors = [];
    page.on('console',message => {if(message.type() === 'error') consoleErrors.push(message.text());});
    await page.goto(`http://127.0.0.1:${server.address().port}/amazon_parser.html`);
    const result = await page.evaluate(async () => {
      const html = `<!doctype html><html><head>
        <style>.order-card { color: red; background-image:url(https://parser-fixture.invalid/background.png) }</style>
        <script>globalThis.__amazonScriptRan = true;<\/script>
        <script src="https://parser-fixture.invalid/script.js"><\/script>
        </head><body style="margin: 0" onload="globalThis.__amazonScriptRan = true">
        <div class="order-card" style="display: block">
          <div class="order-header">Order placed October 20, 2026 Total $10.00 Ship to Example Order # 111-0000000-0000001</div>
          <div class="shipment"><span>Arriving tomorrow</span>
            <a href="/dp/B000000001"><img src="https://parser-fixture.invalid/item.jpg" onerror="globalThis.__amazonScriptRan = true" alt="Cable">Cable</a>
            <span>Qty: 1</span>
            <a href="/gp/your-account/ship-track?orderId=111-0000000-0000001&amp;shipmentId=ABC">Track package</a>
          </div>
        </div><p>1 order placed</p></body></html>`;
      const reply = await new Promise(resolve => window.__parserListeners[0]({target:'ieid-html-parser',kind:'list',url:'https://www.amazon.com/your-orders/orders?timeFilter=year-2026&page=0',html},{id:'fixture'},resolve));
      return {reply,scriptRan:Boolean(window.__amazonScriptRan),liveOrderCards:document.querySelectorAll('.order-card').length};
    });
    await page.waitForTimeout(100);
    assert.equal(result.reply.error,undefined);
    assert.equal(result.reply.result.orders[0].orderId,'111-0000000-0000001');
    assert.equal(result.reply.result.orders[0].shipments[0].itemImage,'https://parser-fixture.invalid/item.jpg');
    assert.equal(result.scriptRan,false);
    assert.equal(result.liveOrderCards,0);
    assert.deepEqual(externalRequests,[]);
    const inlineStyleErrors = consoleErrors.filter(text=>/inline style/i.test(text) && /Content Security Policy/i.test(text));
    assert.deepEqual(inlineStyleErrors,[],'Amazon CSS should not produce parser CSP errors');
    // A separate document with the parser's exact policy must still reject inline scripts.
    const policy = await page.locator('meta[http-equiv="Content-Security-Policy"]').getAttribute('content');
    const probe = await context.newPage();
    await probe.route('**/policy-probe.html',route=>route.fulfill({contentType:'text/html',body:`<meta http-equiv="Content-Security-Policy" content="${policy}"><script>window.__inlineRan = true;<\/script><script src="https://parser-fixture.invalid/probe.js"><\/script><link rel="stylesheet" href="https://parser-fixture.invalid/probe.css"><img src="https://parser-fixture.invalid/probe.png"><iframe src="https://parser-fixture.invalid/probe.html"></iframe>`}));
    await probe.goto(`http://127.0.0.1:${server.address().port}/policy-probe.html`);
    assert.equal(await probe.evaluate(()=>Boolean(window.__inlineRan)),false);
    assert.deepEqual(externalRequests,[],'The parser policy must still block remote resources');
    await context.close();
  } finally {if(browser) await browser.close();await new Promise(r=>server.close(r));}
});
