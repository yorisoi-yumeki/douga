// HTML を PNG に変換する（生成.py から呼ばれる）
const { chromium } = require('playwright');
const fs = require('fs');

(async () => {
  const 指示書 = JSON.parse(fs.readFileSync(process.argv[2], 'utf-8'));
  const ブラウザ = await chromium.launch();
  const ページ = await ブラウザ.newPage({
    viewport: { width: 指示書.幅, height: 指示書.高さ },
    deviceScaleFactor: 指示書.倍率,
  });
  let 検査済み = false;
  for (const 仕事 of 指示書.指示) {
    await ページ.goto('file://' + 仕事.html);

    // 書体を明示的に読み込ませる。
    // ⚠ 文字が1つも無いページ（P1など）では、待つだけでは読み込まれない
    await ページ.evaluate(async () => {
      await Promise.all([...document.fonts].map((f) => f.load()));
      await document.fonts.ready;
    });

    if (!検査済み) {
      const 結果 = await ページ.evaluate(() =>
        [...document.fonts].map((f) => `${f.family} ${f.weight} ${f.status}`)
      );
      if (結果.some((x) => !x.endsWith('loaded')) || 結果.length === 0) {
        console.error('✗ 書体が読み込めていない:', JSON.stringify(結果));
        process.exit(1);
      }
      console.log('  書体を確認: ' + 結果.join(' / '));
      検査済み = true;
    }
    await ページ.screenshot({ path: 仕事.png });
  }
  await ブラウザ.close();
  console.log(`  ${指示書.指示.length}枚を書き出した（${指示書.幅}×${指示書.高さ} の${指示書.倍率}倍）`);
})();
