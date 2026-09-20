import { chromium } from 'playwright'
const [,, url, out, waitMs = '4000', w = '1600', h = '1000'] = process.argv
const browser = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist', '--enable-gpu-rasterization'] })
const page = await browser.newPage({ viewport: { width: +w, height: +h }, deviceScaleFactor: 1 })
const errors = []
page.on('console', m => { if (m.type() === 'error' || m.type() === 'warning') errors.push(`[${m.type()}] ${m.text().slice(0, 300)}`) })
page.on('pageerror', e => errors.push(`[pageerror] ${e.message}`))
await page.goto(url, { waitUntil: 'load' })
await page.waitForTimeout(+waitMs)
await page.screenshot({ path: out })
console.log('saved', out)
console.log(errors.slice(0, 20).join('\n'))
await browser.close()
