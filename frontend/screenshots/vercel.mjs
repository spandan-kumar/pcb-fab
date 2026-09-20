import { chromium } from 'playwright'
const base = process.argv[2] ?? 'https://pcb-fab.vercel.app'
const browser = await chromium.launch({ args: ['--use-angle=metal', '--ignore-gpu-blocklist'] })
const page = await browser.newPage({ viewport: { width: 1500, height: 940 } })
const errs = []; page.on('pageerror', e => errs.push(e.message.slice(0, 200)))
await page.goto(base, { waitUntil: 'load' }); await page.waitForTimeout(3500)
await page.screenshot({ path: 'screenshots/vercel_landing.png' })
console.log('demo cards:', await page.locator('.demo-card').count(), '| health text:', await page.locator('.health').innerText())
await page.locator('.demo-card').first().click()
await page.waitForTimeout(1500)
await page.getByRole('button', { name: '5×', exact: true }).click().catch(() => {})
const t0 = Date.now()
while (Date.now() - t0 < 150000) { await page.waitForTimeout(4000); if (/BOARD COMPLETE/.test(await page.locator('body').innerText())) break }
await page.waitForTimeout(2000)
await page.screenshot({ path: 'screenshots/vercel_final.png' })
console.log('complete:', /BOARD COMPLETE/.test(await page.locator('body').innerText()), 'in', ((Date.now() - t0) / 1000).toFixed(0), 's; errors:', errs.join(' | ') || 'none')
await browser.close()
