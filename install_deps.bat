@echo off
set PROJ=C:\Users\Jacob Higgins\projects\kronos-predictor
set PIP=%PROJ%\venv\Scripts\pip.exe
set PYTHON=%PROJ%\venv\Scripts\python.exe

echo [1/4] Installing PyTorch with CUDA 12.8 support...
"%PIP%" install torch torchvision --index-url https://download.pytorch.org/whl/cu128 --quiet
if %errorlevel% neq 0 (
    echo PyTorch cu128 failed, trying cu121...
    "%PIP%" install torch torchvision --index-url https://download.pytorch.org/whl/cu121 --quiet
)

echo [2/4] Installing Kronos core dependencies...
"%PIP%" install einops==0.8.1 huggingface_hub==0.33.1 matplotlib==3.9.3 pandas==2.2.2 tqdm==4.67.1 safetensors==0.6.2 numpy --quiet

echo [3/4] Installing webui dependencies...
"%PIP%" install flask==2.3.3 flask-cors==4.0.0 plotly==5.17.0 --quiet

echo [4/4] Installing live data feed dependencies...
"%PIP%" install yfinance ccxt requests --quiet

echo ALL DONE
