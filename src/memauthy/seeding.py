"""Seed every source of randomness used in experiments."""

from __future__ import annotations

import os
import random


def seed_everything(seed: int) -> int:
    """Seed Python's ``random`` and, if installed, numpy.

    ``PYTHONHASHSEED`` is also set so that subprocesses started afterwards hash deterministically.
    """
    random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    try:
        import numpy as np
    except ImportError:
        pass
    else:
        np.random.seed(seed % 2**32)
    return seed
