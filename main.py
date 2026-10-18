"""Start G4Speak from a source checkout or a bundled Windows executable."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))
from g4speak.app import main, smoke_test

if __name__ == "__main__":
    if "--smoke-test" in sys.argv:
        smoke_test()
    else:
        main()
