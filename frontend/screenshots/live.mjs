// Live end-to-end: drive the real backend through the UI. Usage: node screenshots/live.mjs [exampleIndex]
import { chromium } from 'playwright'
const idx = Number(process.argv[2] ?? 0)
const browser = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] })
const page = await browser.newPage({ viewport: { width: 1500, height: 940 } })
const errs = []; page.on('pageerror', e => errs.push(e.message.slice(0, 300)))
page.on('console', m => { if (m.type() === 'error') errs.push('console: ' + m.text().slice(0, 200)) })
await page.goto('http://localhost:5173/', { waitUntil: 'load' })
await page.waitForTimeout(2500)
await page.screenshot({ path: 'screenshots/live_landing.png' })
const chips = page.locator('button.chip')
console.log('chips:', await chips.count())
await chips.nth(idx).click()
await page.waitForTimeout(300)
await page.getByRole('button', { name: /FORGE/ }).click()
const t0 = Date.now()
let done = false
let shot = 0
while (Date.now() - t0 < 420000) {
  await page.waitForTimeout(5000)
  const txt = await page.locator('body').innerText()
  const stage = (txt.match(/COMPLETE|NETS \d+\/\d+/) || [''])[0]
  if ((Date.now() - t0) / 1000 > shot * 20) {
    await page.screenshot({ path: `screenshots/live_${String(shot).padStart(2, '0')}.png` }); shot++
    console.log(`${((Date.now() - t0) / 1000).toFixed(0)}s`, stage)
  }
  if (/BOARD COMPLETE/.test(txt) || /COMPLETE/.test(stage)) { done = true; break }
  if (/ERROR/.test(txt) && /engine|failed/i.test(txt)) { console.log('error state'); break }
}
await page.waitForTimeout(2500)
await page.screenshot({ path: 'screenshots/live_final.png' })
for (const tab of ['SCHEMATIC', 'LAYERS', 'THERMAL']) {
  await page.getByRole('button', { name: tab, exact: true }).click(); await page.waitForTimeout(2500)
  await page.screenshot({ path: `screenshots/live_${tab.toLowerCase()}.png` })
}
await page.evaluate(() => { document.querySelectorAll('.scroll').forEach(e => e.scrollTop = e.scrollHeight) })
await page.waitForTimeout(500)
await page.screenshot({ path: 'screenshots/live_output.png' })
console.log('done:', done, 'elapsed', ((Date.now() - t0) / 1000).toFixed(0), 's')
console.log('page errors:', errs.slice(0, 10).join('\n') || 'none')
await browser.close()
