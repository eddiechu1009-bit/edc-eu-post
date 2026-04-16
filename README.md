# EDC EU POST | 跨境電商情報站

Everyday Object 風格的線上新聞資訊站，自動從日報 HTML 解析新聞，部署到 GitHub Pages。

## 功能

- 雜誌風格卡片式佈局
- 分類篩選：精選、稅務、合規、總經、平台、物流、貿易
- 全文搜尋（標題、摘要、影響分析）
- 精選機制：週報內容自動去重，與日報合併後標記為「精選」
- 響應式設計（手機 / 平板 / 桌面）
- 關鍵日期側邊欄
- 點擊卡片展開完整 Impact + Action + Source

## 本地預覽

```bash
python eu-intel-site/build.py
cd eu-intel-site
python -m http.server 8080
# 開啟 http://localhost:8080
```

## 自動部署

推送新日報到 `main` 分支 → GitHub Actions 自動重建並部署到 GitHub Pages。
