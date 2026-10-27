const path = require('path');
const root = path.resolve(__dirname, '../../..');
const { chromium } = require(path.join(root, 'frontend/node_modules/@playwright/test'));
const fs = require('fs');
if (!['before', 'after'].includes(process.argv[2])) throw Error('Usage: node capture.cjs before|after');
const rows = JSON.parse(fs.readFileSync(root + '/backend/analysis/chart/serving/previews/2026-09-21/snapshots.json')).map(payload => {
  payload.inference.contribution_space = 'class_0_raw_margin';
  payload.inference.scores = {down:.7, neutral:.2, up:.1};
  payload.inference.contribution_abs_sum = 1;
  payload.inference.features = [
    {name:'std_20',label_ko:'20일 종가 변동 폭',meaning_ko:'20거래일 기간 종가 표준편차 / 현재 종가',value:.03,contribution:.12},
    {name:'rsqr_20',label_ko:'20일 가격 추세 적합도',meaning_ko:'20거래일 기간 선형 추세가 종가 변동을 설명하는 비율',value:.65,contribution:-.10},
    {name:'cord_20',label_ko:'20일 변화율 상관',meaning_ko:'20거래일 기간 종가 변화율과 거래량 변화율의 상관',value:.2,contribution:.06},
    {...payload.inference.features[3],contribution:-.04},
    {...payload.inference.features[4],contribution:.02},
  ];
  return {stock_code:payload.stock_code,horizon:payload.horizon,batch_id:payload.batch_id,payload};
});
fs.writeFileSync(root + '/docs/qa/2026-10-27-model-reasons/capture-fixture.json', JSON.stringify(rows, null, 2));
(async()=>{
 const browser=await chromium.launch({headless:true});
 for(const [device,width] of [['desktop',1200],['mobile',390]]) {
  const page=await browser.newPage({viewport:{width,height:1000},deviceScaleFactor:1});
  await page.route('**/rest/v1/latest_chart_signal_snapshots?**',route=>route.fulfill({json:rows}));
  await page.goto('http://localhost:3191/stocks/005930');
  await page.getByRole('tab',{name:'모델이 본 이유',exact:true}).click();
  const panel=page.getByRole('tabpanel');
  await panel.locator('[data-model-feature]').first().waitFor();
  await page.evaluate(()=>document.fonts.ready);
  await panel.screenshot({style:'nextjs-portal, header { visibility: hidden !important; }',path:`${root}/docs/qa/2026-10-27-model-reasons/${process.argv[2]}-${device}.png`});
  await panel.locator('summary',{hasText:'계산 근거'}).click();
  await panel.screenshot({style:'nextjs-portal, header { visibility: hidden !important; }',path:`${root}/docs/qa/2026-10-27-model-reasons/${process.argv[2]}-${device}-basis.png`});
  if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)) throw Error('horizontal overflow');
  if (process.argv[2] === 'after') {
    await panel.locator('summary', {hasText:'계산 근거'}).click();
    await panel.scrollIntoViewIfNeeded();
    await panel.locator('[data-model-feature]').first().getByRole('button', {name:/설명 보기$/}).hover();
    await page.getByRole('region', {name:'20일 주가 출렁임 설명',exact:true}).waitFor();
    await panel.screenshot({style:'nextjs-portal, header { visibility: hidden !important; }',path:`${root}/docs/qa/2026-10-27-model-reasons/after-${device}-info.png`});
  }
  await page.close();
 }
 await browser.close();
})();
