@echo off
chcp 65001 >nul
echo ============================================
echo  打包 TBH 效率計算機（單一 exe 版）
echo ============================================
echo.

if exist build rmdir /s /q build
if exist dist rmdir /s /q dist

REM --onefile：單一 exe（避免使用者解壓縮漏檔導致閃退）
REM --windowed：無黑框  --noupx：避免 UPX 壓縮（會增加防毒誤判）
REM --exclude-module：排除程式用不到的大型套件（torch/CUDA 等，會把容量灌到數 GB）
python -m PyInstaller --noconfirm --onefile --windowed --noupx ^
  --name "TBH效率計算機" ^
  --hidden-import win32gui --hidden-import win32api ^
  --collect-all dxcam --collect-all comtypes ^
  --exclude-module torch --exclude-module torchvision --exclude-module torchaudio ^
  --exclude-module scipy --exclude-module matplotlib --exclude-module pandas ^
  --exclude-module tensorflow --exclude-module cv2 --exclude-module IPython ^
  tbh_calc.pyw

echo.
echo 組裝發佈資料夾（單一 exe + Tesseract + 說明）...
mkdir "dist\TBH效率計算機" 2>nul
move /y "dist\TBH效率計算機.exe" "dist\TBH效率計算機\TBH效率計算機.exe" >nul

echo 複製精簡版 Tesseract-OCR（只含英文語言，避免容量過大）...
set "TSRC=C:\Program Files\Tesseract-OCR"
set "TDST=dist\TBH效率計算機\Tesseract-OCR"
robocopy "%TSRC%" "%TDST%" /np /njh /njs /ndl >nul
robocopy "%TSRC%\tessdata" "%TDST%\tessdata" eng.traineddata osd.traineddata /np /njh /njs /ndl >nul
robocopy "%TSRC%\tessdata\configs" "%TDST%\tessdata\configs" /e /np /njh /njs /ndl >nul
robocopy "%TSRC%\tessdata\tessconfigs" "%TDST%\tessdata\tessconfigs" /e /np /njh /njs /ndl >nul

echo.
echo 複製使用說明...
copy /y "使用說明.txt" "dist\TBH效率計算機\使用說明.txt" >nul

echo.
echo ============================================
echo  完成！成品在 dist\TBH效率計算機\
echo  exe 為單一檔，把整個資料夾壓縮後傳給別人即可
echo ============================================
echo.
pause
