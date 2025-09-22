# Local GPU Setup (No Docker)

1. **Install NVIDIA stack**
   - Install the latest NVIDIA display driver that supports your GPU.
   - Install a CUDA Toolkit version compatible with the PyTorch build you intend to use (see https://pytorch.org/get-started/locally/ for matrix).
   - Install cuDNN for the same CUDA version and copy the `bin`, `include`, and `lib` directories into your CUDA installation path.
   - Verify the installation with `nvidia-smi` and `nvcc --version`.

2. **Install Python dependencies with CUDA wheels**
   ```bash
   python -m pip install --upgrade pip
   python -m pip install --index-url https://download.pytorch.org/whl/cu126 torch torchvision torchaudio
   python -m pip install -r requirements.txt
   ```
   Replace `cu126` with the CUDA build you selected.

3. **Verify GPU availability inside the project**
   ```bash
   python - <<'PY'
   import torch
   print('torch.cuda.is_available():', torch.cuda.is_available())
   if torch.cuda.is_available():
       print('GPU:', torch.cuda.get_device_name(0))
   PY
   ```

4. **Run a TrOCR smoke test (optional)**
   ```bash
   python - <<'PY'
   from transformers import TrOCRProcessor, VisionEncoderDecoderModel
   import torch

   processor = TrOCRProcessor.from_pretrained('microsoft/trocr-base-printed')
   model = VisionEncoderDecoderModel.from_pretrained('microsoft/trocr-base-printed').to('cuda')
   dummy = torch.zeros((1, 3, 384, 384), device='cuda')
   out = model.generate(dummy, max_length=4)
   print('Generated tokens:', out)
   PY
   ```

5. **Configure the application**
   - Set `GPU_DEVICE=cuda` in `.env` (or `cuda:<id>` for multi-GPU hosts).
   - Flip `ENABLE_TROCR=1` if you have downloaded the TrOCR weights and want OCR fallback.
   - Ensure `ENABLE_LATE_FUSION_MODEL=1` and provide a trained model in `models/late_fusion_model.pkl`.

6. **Run smoke tests**
   ```bash
   python main.py --test https://example.com
   ```
   Watch `brand_protection.log` and `data/logs/watcher_errors.jsonl` for issues.
