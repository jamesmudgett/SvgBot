"""Print StarVector config + CUDA status (run from backend with PYTHONPATH=.)."""
from __future__ import annotations

import sys

from app.config import starvector_config_debug
from app.services.starvector_engine import availability


def main() -> int:
    print("=== StarVector diagnostics ===\n")
    cfg = starvector_config_debug()
    for k, v in cfg.items():
        print(f"  {k}: {v}")

    try:
        import torch

        print(f"\n  torch: {torch.__version__}")
        print(f"  torch.cuda.is_available(): {torch.cuda.is_available()}")
        if torch.cuda.is_available():
            print(f"  GPU: {torch.cuda.get_device_name(0)}")
        elif "+cpu" in torch.__version__ or not torch.version.cuda:
            print(
                "\n  PyTorch appears CPU-only. Install a CUDA build, e.g.:\n"
                "    pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124"
            )
    except ImportError:
        print("\n  torch not installed")

    print("\n=== availability() ===")
    av = availability()
    for k, v in av.items():
        print(f"  {k}: {v}")

    if not av["ready"]:
        print("\nFix the issue above, then restart uvicorn (kill any old process on port 8000).")
        return 1
    print("\nStarVector is ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
