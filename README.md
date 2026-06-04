# TBH 效率計算機（Lite 版）

給 Steam 遊戲 **TBH: Task Bar Hero（塔斯克巴·英雄）** 用的掛機效率計算工具。

透過螢幕 OCR 即時讀取金幣與經驗，計算每秒/分鐘/小時的產出速率，
方便比較不同關卡的掛機效率、估算升級時間。

> **Lite 版**：只用畫面 OCR 截圖讀取數值，**不讀取遊戲記憶體、不自動點擊、不做任何修改**，純屬外部觀察工具。

## ⬇️ 下載

**[👉 點此下載最新版 exe（Releases）](https://github.com/poison0215/TBH-Efficiency-Calculator/releases/latest)**

下載 `TBH-Efficiency-Calculator-vX.X.X.zip` → 解壓縮 → 雙擊 `TBH效率計算機.exe`
（已內含 Tesseract，**不需安裝 Python 或其他東西**）

### ⚠️ 防毒軟體可能誤判

本程式用 PyInstaller 打包，**Windows Defender 或防毒軟體可能誤報為病毒**。
這是 PyInstaller 打包程式常見的**誤判（false positive）**，本工具不含任何惡意程式，
原始碼完全公開可檢視。

若被攔截，請：

- **Windows SmartScreen**「不明發行者」警告 → 點「**更多資訊**」→「**仍要執行**」
- **Windows Defender** 攔截 → 到「病毒與威脅防護」→「保護歷程記錄」→ 對該項目選「**允許**」
- 不放心可自行用 `build.bat` 從原始碼打包，或直接 `python tbh_calc.pyw` 執行

## 功能

- **即時監控**：金幣 / 經驗的每秒・每分・每時速率（全程累計平均 + 離群值過濾）
- **升級進度**：進度條 + 預計升級時間
- **關卡比較**：保存各關卡數據、排序比較，自動標示最佳效率
- **自動保存**：設定監測時間，到時自動存入比較表
- **區域設定**：拖曳框選金幣/經驗位置，即時 OCR 預覽
- **雙語介面**：中文 / English，右上角按鈕即時切換（Bilingual UI, switchable）

## 需求

- Windows
- Python 3.10+（若直接跑原始碼）
- 套件：`pip install -r requirements.txt`
- [Tesseract OCR](https://github.com/UB-Mannheim/tesseract/wiki)

## 使用

直接執行原始碼：

```
python tbh_calc.pyw
```

或用 `build.bat` 打包成獨立執行檔（會內含 Tesseract，對方免安裝）。

詳細操作見 `使用說明.txt`。

## 授權

個人用途，僅供學習參考。
