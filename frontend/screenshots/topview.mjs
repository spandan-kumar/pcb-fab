import { chromium } from 'playwright'
const rid = process.argv[2] ?? 'beb142f016'
const browser = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] })
const page = await browser.newPage({ viewport: { width: 1500, height: 940 }, deviceScaleFactor: 2 })
await page.goto(`http://localhost:5173/?replay=${rid}&speed=5&view=top`, { waitUntil: 'load' })
const t0 = Date.now()
while (Date.now() - t0 < 120000) { await page.waitForTimeout(3000); if (/BOARD COMPLETE/.test(await page.locator('body').innerText())) break }
await page.waitForTimeout(3000)
const canvas = page.locator('.canvas-wrap canvas').first()
await canvas.screenshot({ path: `screenshots/top_${rid}.png` })
console.log('saved', `screenshots/top_${rid}.png`)
await browser.close()
