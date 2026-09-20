import { chromium } from 'playwright'
const [,, url, prefix, times = '5000,10000,16000', w = '1400', h = '900'] = process.argv
const browser = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] })
const page = await browser.newPage({ viewport: { width: +w, height: +h } })
const errors = []
page.on('console', m => { if (m.type() === 'error') errors.push(m.text().slice(0, 200)) })
page.on('pageerror', e => errors.push('PAGEERROR ' + e.message.slice(0, 300)))
await page.goto(url, { waitUntil: 'load' })
let last = 0
for (const t of times.split(',').map(Number)) {
  await page.waitForTimeout(t - last); last = t
  await page.screenshot({ path: `${prefix}_${t}.png` })
  const st = await page.evaluate(() => { const s = window.__etch?.getState(); return s ? `${s.stage} tab=${s.tab} traces=${s.traces.length} elapsed=${s.elapsed}` : 'no store' })
  console.log('shot', t, st)
}
console.log(errors.filter(e => !/502/.test(e)).slice(0, 10).join('\n'))
await browser.close()
